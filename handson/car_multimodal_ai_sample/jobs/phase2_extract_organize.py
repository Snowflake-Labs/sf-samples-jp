"""Phase 2 — extract & organize: decode HEVC, sync sensors, generate radar-based
labels, crop frames, and stage images + build the SENSORS/SPLITS tables.

The label-generation, sensor-sync, and crop logic below is ported unchanged
from the validated 45-minute handson (`car_multimodal_handson/prepare/stage_chunk1.py`)
— it is NOT redesigned here. Only the I/O changed: input comes
from `@RAW_STAGE` (Phase 1) instead of a local directory, and output goes to
`@IMAGES_STAGE` + the `SENSORS`/`SPLITS` tables instead of local files.

Runs as a Snowflake ML Job on `MULTIMODAL_CPU_POOL`. Segment processing is
submitted as Ray remote tasks (one task per segment); Ray's scheduler spreads
these tasks across every node in the cluster. **Default is 4 nodes**
(`scripts/submit_phase2.py --nodes 4` is the default, not opt-in) — this
script never checks the node count itself; whatever `--nodes N` was passed at
submission time (mapped to `submit_directory(..., target_instances=N)`)
determines how many nodes Container Runtime forms the Ray cluster from, and
`ray.nodes()` just reports whatever cluster it actually landed on. This data
volume (188 segments) doesn't strictly need 4 nodes for speed, but 4 is the
default anyway so this phase demonstrates real multi-node distribution out of
the box. Pass `--nodes 1` for a single-node run.
Each task opens its own Snowpark session via `SnowflakeLoginOptions()`
(reads the container's own OAuth token / `SNOWFLAKE_*` env vars) rather than
`get_active_session()` — that only works in the process that already has a
session registered (the driver); a fresh Ray worker process has none
(confirmed via real error: `SnowparkSessionException: (1403): No default
Session is found`).

Usage:

    python jobs/phase2_extract_organize.py --dry-run --limit 3
    python jobs/phase2_extract_organize.py                     # full Chunk_1
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import click
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import get_logger, load_config, resolve  # noqa: E402

LOG = get_logger("phase2_extract_organize")

WORKDIR = Path("/tmp/car_multimodal_phase2")
RADAR_FWD, RADAR_LAT, RADAR_REL = 0, 1, 2


# --------------------------------------------------------------------------- #
# comma2k19 readers (ported from stage_chunk1.py, unchanged)
# --------------------------------------------------------------------------- #
def load_log(seg: Path, rel: str) -> tuple[np.ndarray, np.ndarray] | None:
    base = seg / "processed_log" / rel
    t_path, v_path = base / "t", base / "value"
    if not t_path.exists() or not v_path.exists():
        return None
    return np.load(t_path, allow_pickle=False), np.load(v_path, allow_pickle=False)


def load_frame_times(seg: Path) -> np.ndarray:
    """Camera frame timestamps (global_pose, not `header`)."""
    return np.load(seg / "global_pose" / "frame_times", allow_pickle=False)


def compute_labels(
    radar_t: np.ndarray, radar_val: np.ndarray, frame_times: np.ndarray, cfg: dict[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    """Lead distance [m] and relative speed [m/s] per camera frame."""
    tol = float(cfg["label"]["radar_time_tol_s"])
    half = float(cfg["label"]["ego_lane_half_width_m"])
    dmin = float(cfg["label"]["min_distance_m"])
    dmax = float(cfg["label"]["max_distance_m"])

    fwd = radar_val[:, RADAR_FWD].astype(np.float64)
    lat = radar_val[:, RADAR_LAT].astype(np.float64)
    rel = radar_val[:, RADAR_REL].astype(np.float64)
    valid = (
        np.isfinite(fwd) & np.isfinite(lat) & (np.abs(lat) < half) & (fwd >= dmin) & (fwd <= dmax)
    )

    order = np.argsort(radar_t)
    rt = radar_t[order]
    dist_out = np.full(frame_times.shape[0], np.nan)
    rel_out = np.full(frame_times.shape[0], np.nan)
    lo_all = np.searchsorted(rt, frame_times - tol, side="left")
    hi_all = np.searchsorted(rt, frame_times + tol, side="right")
    for i in range(frame_times.shape[0]):
        idx = order[lo_all[i] : hi_all[i]]
        idx = idx[valid[idx]]
        if idx.size == 0:
            continue
        j = idx[np.argmin(fwd[idx])]
        dist_out[i] = fwd[j]
        rel_out[i] = rel[j]
    return dist_out, rel_out


def _nearest_sample(t: np.ndarray, value: np.ndarray, query: np.ndarray) -> np.ndarray:
    order = np.argsort(t)
    ts, vs = t[order], value[order]
    pos = np.clip(np.searchsorted(ts, query), 1, len(ts) - 1)
    left, right = ts[pos - 1], ts[pos]
    idx = np.where((query - left) <= (right - query), pos - 1, pos)
    return vs[idx]


def sync_sensors(seg: Path, frame_times: np.ndarray, channels: list[str]) -> np.ndarray:
    """Ego-motion matrix synced to camera frame times."""
    speed, steer, wheel = load_log(seg, "CAN/speed"), load_log(seg, "CAN/steering_angle"), load_log(
        seg, "CAN/wheel_speed"
    )
    accel, gyro = load_log(seg, "IMU/accelerometer"), load_log(seg, "IMU/gyro")

    def col(series, axis):
        if series is None:
            return np.full(frame_times.shape[0], np.nan)
        t, v = series
        v = np.asarray(v, dtype=np.float64)
        vv = v if v.ndim == 1 else (np.nanmean(v, axis=1) if axis is None else v[:, axis])
        return _nearest_sample(t, vv, frame_times)

    lookup = {
        "speed": lambda: col(speed, None),
        "steering_angle": lambda: col(steer, None),
        "wheel_speed_mean": lambda: col(wheel, None),
        "accel_x": lambda: col(accel, 0),
        "accel_y": lambda: col(accel, 1),
        "accel_z": lambda: col(accel, 2),
        "gyro_x": lambda: col(gyro, 0),
        "gyro_y": lambda: col(gyro, 1),
        "gyro_z": lambda: col(gyro, 2),
    }
    cols = [lookup[name]() for name in channels]
    return np.stack(cols, axis=1).astype(np.float32)


def apply_crop(frame: np.ndarray, crop: dict | None) -> np.ndarray:
    """Crop to the lower-centre road region. No-op if disabled."""
    if not crop or not crop.get("enabled", False):
        return frame
    h, w = frame.shape[:2]
    return frame[
        int(h * crop["top"]) : int(h * crop["bottom"]),
        int(w * crop["left"]) : int(w * crop["right"]),
    ]


def decode_keep_frames(seg: Path, stride: int) -> tuple[list[int], list[np.ndarray]]:
    import av

    kept_idx: list[int] = []
    kept_frames: list[np.ndarray] = []
    with av.open(str(seg / "video.hevc")) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for i, frame in enumerate(container.decode(stream)):
            if i % stride == 0:
                kept_frames.append(frame.to_ndarray(format="rgb24"))
                kept_idx.append(i)
    return kept_idx, kept_frames


# --------------------------------------------------------------------------- #
# Per-segment processing (called as a Ray remote task, one seg per task)
# --------------------------------------------------------------------------- #
def get_segment(session, stage: str, seg_id: str, local_dir: Path) -> None:
    """Download all of a segment's files from the stage, preserving subdirectories.

    Snowflake stage GET/LIST matching is prefix-based on the raw key string,
    not exact-path-segment based — `GET @stage/.../gyro` also matches sibling
    keys like `.../gyro_bias/...` and `.../gyro_uncalibrated/...` because they
    share the "gyro" string prefix, silently merging their same-named `t`/
    `value` files into one target directory. To avoid this, GET each file
    individually using its exact full stage key (unambiguous), into the local
    directory matching its exact relative parent path.
    """
    rows = session.sql(f"LIST '{stage}/{seg_id}/'").collect()
    for row in rows:
        # row[0] looks like "<stage_name>/<seg_id>/processed_log/CAN/radar/t"
        full_path = row[0]
        idx = full_path.find(f"{seg_id}/")
        rel = Path(full_path[idx + len(seg_id) + 1 :])
        target = local_dir if str(rel.parent) == "." else local_dir / rel.parent
        session.file.get(f"{stage}/{seg_id}/{rel.as_posix()}", str(target))


def process_segment(seg_id: str, cfg: dict, raw_stage: str, images_stage: str) -> dict:
    """Pull one segment from RAW_STAGE, decode+label+crop, push crops to IMAGES_STAGE.

    Runs as a Ray remote task (see `_process_segments_distributed` below),
    potentially on a different node than the driver. `get_active_session()`
    only returns a session in the process that already has one registered
    (the driver) — a fresh Ray worker process has none (confirmed via real
    error: `SnowparkSessionException: (1403): No default Session is found`).
    Each task instead opens its own session via `SnowflakeLoginOptions()`,
    which reads the container's own OAuth token
    (`/snowflake/session/token`) / `SNOWFLAKE_*` env vars — the same
    connection mechanism every node in the job's compute pool has, not just
    the head node.

    Returns a dict of arrays ready to become SENSORS rows, or {"seg_id", "error"}.
    """
    from PIL import Image

    from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
    from snowflake.snowpark import Session

    local_dir = WORKDIR / seg_id
    local_dir.mkdir(parents=True, exist_ok=True)
    session = None
    try:
        session = Session.builder.configs(SnowflakeLoginOptions()).create()
        get_segment(session, raw_stage, seg_id, local_dir)
        seg = local_dir

        stride = int(cfg["sampling"]["source_hz"] // cfg["sampling"]["target_hz"])
        frame_times = load_frame_times(seg)
        radar = load_log(seg, "CAN/radar")
        if radar is None:
            return {"seg_id": seg_id, "error": "no radar channel"}

        kept_idx, frames = decode_keep_frames(seg, stride)
        if not frames:
            return {"seg_id": seg_id, "error": "no frames decoded"}
        kept_idx = [i for i in kept_idx if i < len(frame_times)]
        frames = frames[: len(kept_idx)]
        kt = frame_times[kept_idx]

        dist_full, rel_full = compute_labels(radar[0], radar[1], frame_times, cfg)
        dist, rel = dist_full[kept_idx], rel_full[kept_idx]
        sensors = sync_sensors(seg, kt, cfg["sensor_channels"])[: len(kept_idx)]

        crop_cfg = cfg["features"].get("crop")
        thumb = cfg["thumbnail"]
        ids = [f"{seg_id}_{i:04d}" for i in kept_idx]
        crop_dir, full_dir = local_dir / "cropped", local_dir / "full"
        crop_dir.mkdir(exist_ok=True)
        full_dir.mkdir(exist_ok=True)
        for frame, sid in zip(frames, ids, strict=True):
            cropped = apply_crop(frame, crop_cfg)
            Image.fromarray(cropped).save(crop_dir / f"{sid}.jpg", quality=thumb["quality"])
            Image.fromarray(frame).resize(
                (thumb["width"], thumb["height"]), Image.BILINEAR
            ).save(full_dir / f"{sid}.jpg", quality=thumb["quality"])

        # auto_compress=False: JPEGs are already compressed, and Phase 5's
        # SFStageImageDataSource matches on a literal ".jpg" extension — the
        # default gzip-on-PUT would silently rename these to "*.jpg.gz" and
        # Phase 5 would find zero files (confirmed via real error).
        session.file.put(
            str(crop_dir / "*.jpg"), f"{images_stage}/cropped/", auto_compress=False, overwrite=True
        )
        session.file.put(
            str(full_dir / "*.jpg"), f"{images_stage}/full/", auto_compress=False, overwrite=True
        )

        return {
            "seg_id": seg_id,
            "ids": ids,
            "frame_idx": kept_idx,
            "t": kt.astype(np.float64),
            "sensors": sensors,
            "distance": dist.astype(np.float32),
            "rel_speed": rel.astype(np.float32),
        }
    except Exception as exc:  # noqa: BLE001 - report and skip, don't kill the batch
        return {"seg_id": seg_id, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(local_dir, ignore_errors=True)
        if session is not None:
            session.close()


def _process_segments_distributed(
    seg_ids: list[str], cfg: dict, raw_stage: str, images_stage: str
) -> list[dict]:
    """Submit one Ray remote task per segment; Ray's scheduler spreads them across
    every node currently in the cluster (1 node if `target_instances=1`, N nodes
    if the job was submitted with `--nodes N` — see module docstring).
    """
    import ray

    if not ray.is_initialized():
        ray.init(address="auto", ignore_reinit_error=True)
    LOG.info("Ray cluster: %d node(s) available", len(ray.nodes()))

    remote_process_segment = ray.remote(process_segment)
    futures = [
        remote_process_segment.remote(seg_id, cfg, raw_stage, images_stage) for seg_id in seg_ids
    ]

    results = []
    for i, future in enumerate(futures, start=1):
        result = ray.get(future)
        LOG.info("[%d/%d] processed %s", i, len(futures), result["seg_id"])
        results.append(result)
    return results


def make_splits(seg_ids: list[str], cfg: dict) -> dict[str, str]:
    """Deterministic segment-level train/val/test split."""
    rng = np.random.default_rng(int(cfg["split"]["seed"]))
    ids = sorted(seg_ids)
    rng.shuffle(ids)
    n = len(ids)
    n_tr = int(round(n * float(cfg["split"]["train"])))
    n_va = int(round(n * float(cfg["split"]["val"])))
    return {
        sid: ("train" if k < n_tr else "val" if k < n_tr + n_va else "test")
        for k, sid in enumerate(ids)
    }


def rows_to_dataframe(results: list[dict], channels: list[str]):
    import pandas as pd

    records = []
    for r in results:
        if "error" in r:
            continue
        n = len(r["ids"])
        for i in range(n):
            row = {
                "SAMPLE_ID": r["ids"][i],
                "SEGMENT": r["seg_id"],
                "FRAME_IDX": r["frame_idx"][i],
                "T": r["t"][i],
                "DISTANCE": r["distance"][i],
                "REL_SPEED": r["rel_speed"][i],
            }
            for c_idx, name in enumerate(channels):
                row[name.upper()] = r["sensors"][i, c_idx]
            records.append(row)
    return pd.DataFrame(records)


def run(config: str, limit: int | None, dry_run: bool) -> int:
    cfg = load_config(resolve(config))
    channels = cfg["sensor_channels"]

    from snowflake.snowpark.context import get_active_session

    session = get_active_session()
    raw_stage = cfg["snowflake"]["stages"]["raw"]
    images_stage = cfg["snowflake"]["stages"]["images"]

    seg_rows = session.sql("SELECT SEGMENT_ID FROM RAW.SEGMENTS WHERE STATUS = 'staged'").collect()
    seg_ids = [r["SEGMENT_ID"] for r in seg_rows]
    if limit:
        seg_ids = seg_ids[:limit]
    LOG.info("Processing %d segments", len(seg_ids))

    results = _process_segments_distributed(seg_ids, cfg, raw_stage, images_stage)

    errors = [r for r in results if "error" in r]
    for e in errors:
        LOG.warning("segment %s failed: %s", e["seg_id"], e["error"])
    ok_results = [r for r in results if "error" not in r]
    total_frames = sum(len(r["ids"]) for r in ok_results)
    valid_frames = sum(int(np.isfinite(r["distance"]).sum()) for r in ok_results)
    LOG.info(
        "Segments ok=%d failed=%d | frames=%d valid_labels=%d (%.1f%%)",
        len(ok_results),
        len(errors),
        total_frames,
        valid_frames,
        100.0 * valid_frames / total_frames if total_frames else 0.0,
    )

    if dry_run:
        LOG.info("[dry-run] skipping SENSORS/SPLITS table writes")
        return 0

    if not ok_results:
        LOG.error("All %d segments failed; nothing to write to SENSORS/SPLITS", len(errors))
        return 1

    df = rows_to_dataframe(ok_results, channels)
    session.write_pandas(df, table_name="SENSORS", schema="CURATED", auto_create_table=True, overwrite=False)

    splits = make_splits([r["seg_id"] for r in ok_results], cfg)
    import pandas as pd

    splits_df = pd.DataFrame({"SEGMENT_ID": list(splits.keys()), "SPLIT": list(splits.values())})
    session.write_pandas(splits_df, table_name="SPLITS", schema="CURATED", auto_create_table=True, overwrite=False)

    LOG.info("Wrote %d SENSORS rows, %d SPLITS rows", len(df), len(splits_df))
    return 0


@click.command()
@click.option("--config", default="conf/prepare.yaml", show_default=True)
@click.option("--limit", type=int, default=None, help="process at most N segments")
@click.option("--dry-run", is_flag=True, help="process locally, skip table/stage writes")
def main(config: str, limit: int | None, dry_run: bool) -> None:
    """Phase 2: extract, label, crop, and load tables."""
    sys.exit(run(config, limit, dry_run))


if __name__ == "__main__":
    main()

"""Phase 1 — download comma2k19 raw_data chunk(s) and stage them segment-by-segment
into `@RAW_STAGE`.

Runs as a Snowflake ML Job (`snow ml jobs submit-file`) on `MULTIMODAL_CPU_POOL`
with the `HF_ACCESS_INTEGRATION` external access integration attached. No
HuggingFace token is required (commaai/comma2k19 is public, non-gated —
verified).

Which chunks to ingest is controlled by `conf/prepare.yaml: huggingface.chunks`:
    chunks: ["Chunk_1"]                  # default — 8.73 GB, ~188 segments
    chunks: "all"                        # full dataset — Chunk_1..Chunk_10, ~94.6 GB, ~2,019 segments
    chunks: ["Chunk_1", "Chunk_2"]        # any explicit subset

Chunks are processed one at a time: download -> unzip -> stage -> delete local
copy -> next chunk. Peak local disk usage is therefore bounded by the size of
the single largest chunk (~10 GB), not the sum of all chunks, even when
`chunks: "all"` is used. This chunk-level sequencing is NOT parallelized (it
would defeat the point of bounding peak disk usage).

**Segment staging within a chunk IS parallelized by default** (`--concurrency N`,
default 8): each segment's `stage_segment()` PUT calls are network-upload-bound,
so a thread pool gives a real wall-clock win with no extra compute-pool nodes
needed (this is single-container, single-node concurrency — a different lever
from Phase 2/5/7's multi-node `--nodes` distribution). The single Snowpark
`session` this script starts with (`get_active_session()`) is **not** safe to
share across threads — the same constraint Phase 2 already documented for its
Ray workers (`SnowparkSessionException: No default Session is found` /
concurrent-cursor-use issues) — so each worker thread lazily creates and reuses
its own session (`_thread_session()`), closed explicitly once the pool for a
chunk finishes (`_close_thread_sessions()`), rather than left to the garbage
collector. Pass `--concurrency 1` to fall back to strictly sequential staging.

Usage (inside the ML Job container):

    python jobs/phase1_ingest_raw.py --dry-run --limit 3   # smoke test, 3 segments
    python jobs/phase1_ingest_raw.py                        # ingest configured chunk(s), 8 threads
    python jobs/phase1_ingest_raw.py --concurrency 1         # sequential staging (no threading)

Submit as an ML Job:

    snow ml jobs submit-file jobs/phase1_ingest_raw.py \\
        --compute-pool MULTIMODAL_CPU_POOL \\
        --database CAR_MULTIMODAL_AI_DB --schema RAW \\
        --external-access-integrations HF_ACCESS_INTEGRATION \\
        -- --dry-run --limit 3
"""

from __future__ import annotations

import shutil
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import get_logger, load_config, resolve  # noqa: E402

LOG = get_logger("phase1_ingest_raw")

WORKDIR = Path("/tmp/car_multimodal_phase1")  # ML Job container ephemeral disk
ALL_CHUNKS = [f"Chunk_{i}" for i in range(1, 11)]  # raw_data/Chunk_1.zip .. Chunk_10.zip
DEFAULT_CONCURRENCY = 8  # threads for segment staging; network-upload-bound, not CPU-bound


def resolve_chunks(cfg: dict) -> list[str]:
    """Expand `huggingface.chunks` ("all" | list[str]) into a concrete chunk-name list."""
    chunks = cfg["huggingface"].get("chunks", ["Chunk_1"])
    if isinstance(chunks, str):
        if chunks.lower() != "all":
            raise ValueError(f"huggingface.chunks string value must be 'all', got {chunks!r}")
        return ALL_CHUNKS
    unknown = [c for c in chunks if c not in ALL_CHUNKS]
    if unknown:
        raise ValueError(f"Unknown chunk name(s) {unknown}; valid values are {ALL_CHUNKS}")
    return list(chunks)


def download_chunk(cfg: dict, chunk: str) -> Path:
    """Download one raw_data/<chunk>.zip from HuggingFace (anonymous, no token required)."""
    from huggingface_hub import hf_hub_download

    hf_cfg = cfg["huggingface"]
    filename = f"raw_data/{chunk}.zip"
    dest = WORKDIR / "dl" / chunk
    dest.mkdir(parents=True, exist_ok=True)
    LOG.info("Downloading %s:%s -> %s", hf_cfg["repo_id"], filename, dest)
    path = hf_hub_download(
        repo_id=hf_cfg["repo_id"],
        repo_type=hf_cfg["repo_type"],
        filename=filename,
        local_dir=str(dest),
        token=None,  # public dataset; set only if you hit anonymous rate limits
    )
    size_gb = Path(path).stat().st_size / 1e9
    LOG.info("Downloaded %s (%.2f GB)", path, size_gb)
    return Path(path)


def unzip_chunk(zip_path: Path, chunk: str) -> Path:
    out_dir = WORKDIR / "unzipped" / chunk
    out_dir.mkdir(parents=True, exist_ok=True)
    LOG.info("Unzipping %s -> %s", zip_path, out_dir)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    return out_dir


def find_segments(raw_root: Path) -> list[Path]:
    """All segment directories under raw_root (those containing a video.hevc)."""
    return sorted(p.parent for p in raw_root.rglob("video.hevc"))


def segment_id_for(seg_dir: Path) -> str:
    """Stable segment id: `<drive-hash>_<date--time>_<segment-num>`, slashes -> underscores.

    comma2k19 paths look like `.../b0c9d2329ad1606b|2018-07-27--06-03-57/10`.
    We normalise the `|` (drive id / date-time separator) to `_` for a
    filesystem- and SQL-identifier-safe id. Drive hashes are globally unique
    across chunks, so this stays collision-free even when ingesting "all".
    """
    return f"{seg_dir.parent.name}_{seg_dir.name}".replace("|", "_")


def ensure_segments_table(session) -> None:
    session.sql(
        """
        CREATE TABLE IF NOT EXISTS RAW.SEGMENTS (
            segment_id   VARCHAR NOT NULL,
            chunk        VARCHAR,
            source_path  VARCHAR,
            byte_size    NUMBER,
            has_video    BOOLEAN,
            has_radar    BOOLEAN,
            status       VARCHAR DEFAULT 'staged',
            ingested_at  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    ).collect()


_thread_local = threading.local()
_created_sessions: list = []
_sessions_lock = threading.Lock()


def _thread_session():
    """One Snowpark session per worker thread, created lazily on first use and
    reused for every subsequent segment that same thread stages.

    A Snowpark session/cursor is not safe to share across concurrent threads
    (the same reason Phase 2's Ray workers each open their own session via
    `SnowflakeLoginOptions()` rather than sharing the driver's
    `get_active_session()`). Creating a fresh session per *segment* instead of
    per *thread* would work too, but adds an avoidable network round-trip
    (session auth) for every one of the ~188 segments instead of just the
    (small, fixed) number of worker threads.
    """
    from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
    from snowflake.snowpark import Session

    session = getattr(_thread_local, "session", None)
    if session is None:
        session = Session.builder.configs(SnowflakeLoginOptions()).create()
        _thread_local.session = session
        with _sessions_lock:
            _created_sessions.append(session)
    return session


def _close_thread_sessions() -> None:
    """Explicitly close every session opened by `_thread_session()` so far.

    Called once per chunk, after that chunk's `ThreadPoolExecutor` block exits
    (its worker threads are gone, but the `Session` objects they created are
    still referenced by `_created_sessions` until closed here) — relying on
    garbage collection to eventually close them would leave connections open
    for longer than necessary.
    """
    with _sessions_lock:
        sessions, _created_sessions[:] = list(_created_sessions), []
    for s in sessions:
        try:
            s.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup, not worth failing the run over
            pass


def stage_segment(session, seg_dir: Path, seg_id: str, chunk: str, stage: str) -> dict:
    """PUT one segment's Phase-2-relevant files to `@RAW_STAGE/<seg_id>/...`.

    Only `video.hevc`, `processed_log/**`, and `global_pose/**` are staged —
    `jobs/phase2_extract_organize.py` never reads anything else. The segment's
    `raw_log.bz2` (unparsed capnp log) is deliberately excluded: it is not
    needed downstream.

    A single file's PUT failure marks the segment `corrupt` and moves on
    instead of raising — one bad file must not abort the whole ingestion run.
    """
    include_globs = ["video.hevc", "processed_log/**/*", "global_pose/**/*"]
    files = [f for pattern in include_globs for f in seg_dir.glob(pattern) if f.is_file()]
    byte_size = sum(f.stat().st_size for f in files)
    has_video = (seg_dir / "video.hevc").exists()
    has_radar = (seg_dir / "processed_log" / "CAN" / "radar" / "value").exists()
    status = "staged" if (has_video and has_radar) else "corrupt"

    if status == "staged":
        try:
            for f in files:
                rel = f.relative_to(seg_dir)
                rel_parent = rel.parent.as_posix()
                # For a top-level file (e.g. video.hevc), Path(".").as_posix() == "."
                # — appending that verbatim produces a malformed "<stage>/<seg_id>/."
                # destination that the internal stage rejects with 403 Forbidden
                # (confirmed via isolated repro against real Chunk_1 data: every
                # top-level file failed, every file under a subdirectory succeeded).
                dest = f"{stage}/{seg_id}" if rel_parent == "." else f"{stage}/{seg_id}/{rel_parent}"
                session.file.put(str(f), dest, auto_compress=False, overwrite=True)
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the whole run
            LOG.warning("segment %s failed during PUT (%s); marked corrupt", seg_id, exc)
            status = "corrupt"
    else:
        LOG.warning("segment %s missing video/radar; marked corrupt, not staged", seg_id)

    return {
        "SEGMENT_ID": seg_id,
        "CHUNK": chunk,
        "SOURCE_PATH": str(seg_dir),
        "BYTE_SIZE": byte_size,
        "HAS_VIDEO": has_video,
        "HAS_RADAR": has_radar,
        "STATUS": status,
    }


def stage_segment_threaded(seg_dir: Path, seg_id: str, chunk: str, stage: str) -> dict:
    """`ThreadPoolExecutor` worker: stage one segment using this worker thread's
    own session (`_thread_session()`), never the driver's shared session.

    Mirrors `stage_segment()`'s own contract (never raises — one bad segment
    must not abort the whole chunk) at the thread-pool level too, so a worker
    thread hitting an unexpected error (e.g. failing to even create its
    session) marks that segment `corrupt` instead of propagating and losing
    the rest of the pool's in-flight work.
    """
    try:
        session = _thread_session()
        return stage_segment(session, seg_dir, seg_id, chunk, stage)
    except Exception as exc:  # noqa: BLE001 - one segment must not abort the whole chunk
        LOG.warning("segment %s raised unexpectedly (%s); marked corrupt", seg_id, exc)
        return {
            "SEGMENT_ID": seg_id,
            "CHUNK": chunk,
            "SOURCE_PATH": str(seg_dir),
            "BYTE_SIZE": 0,
            "HAS_VIDEO": False,
            "HAS_RADAR": False,
            "STATUS": "corrupt",
        }


def ingest_chunk(
    cfg: dict, chunk: str, stage: str, limit: int | None, concurrency: int = DEFAULT_CONCURRENCY
) -> list[dict]:
    """Download -> unzip -> stage (in parallel) -> cleanup for a single chunk.

    Returns its ledger rows. `concurrency` threads stage segments concurrently
    within this chunk; chunks themselves are still processed one at a time by
    the caller (see module docstring for why).
    """
    zip_path = download_chunk(cfg, chunk)
    raw_root = unzip_chunk(zip_path, chunk)
    segments = find_segments(raw_root)
    if limit:
        segments = segments[:limit]
    LOG.info("[%s] found %d segments to stage (concurrency=%d)", chunk, len(segments), concurrency)

    rows: list[dict | None] = [None] * len(segments)
    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            future_to_idx = {
                pool.submit(stage_segment_threaded, seg, segment_id_for(seg), chunk, stage): i
                for i, seg in enumerate(segments)
            }
            done = 0
            for future in as_completed(future_to_idx):
                i = future_to_idx[future]
                rows[i] = future.result()
                done += 1
                LOG.info("[%s] [%d/%d] staged %s", chunk, done, len(segments), rows[i]["SEGMENT_ID"])
    finally:
        # Close every session opened by this chunk's worker threads before the
        # next chunk spins up a fresh pool (new threads -> new sessions).
        _close_thread_sessions()

    # Free local disk before starting the next chunk (bounds peak usage to ~1 chunk).
    shutil.rmtree(WORKDIR / "dl" / chunk, ignore_errors=True)
    shutil.rmtree(WORKDIR / "unzipped" / chunk, ignore_errors=True)
    return rows


def run(
    config: str,
    limit: int | None,
    dry_run: bool,
    keep_local: bool,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> int:
    cfg = load_config(resolve(config))
    stage = cfg["snowflake"]["stages"]["raw"]
    chunks = resolve_chunks(cfg)
    LOG.info("Ingesting %d chunk(s): %s", len(chunks), chunks)
    if len(chunks) > 1:
        LOG.warning(
            "Ingesting %d chunks (~%.0f GB total download) — consider the "
            "time/cost implications of switching off the default Chunk_1-only scope.",
            len(chunks),
            len(chunks) * 9.5,
        )

    if dry_run:
        for chunk in chunks:
            zip_path = download_chunk(cfg, chunk)
            raw_root = unzip_chunk(zip_path, chunk)
            segments = find_segments(raw_root)
            if limit:
                segments = segments[:limit]
            LOG.info("[dry-run][%s] found %d segments; skipping stage PUT/table writes", chunk, len(segments))
            for seg in segments[:3]:
                LOG.info("  sample segment: %s (id=%s)", seg, segment_id_for(seg))
            if not keep_local:
                shutil.rmtree(WORKDIR / "dl" / chunk, ignore_errors=True)
                shutil.rmtree(WORKDIR / "unzipped" / chunk, ignore_errors=True)
        return 0

    from snowflake.snowpark.context import get_active_session

    session = get_active_session()
    ensure_segments_table(session)

    all_rows = []
    for chunk in chunks:
        all_rows.extend(ingest_chunk(cfg, chunk, stage, limit, concurrency))

    import pandas as pd

    session.write_pandas(
        pd.DataFrame(all_rows),
        table_name="SEGMENTS",
        database=None,
        schema="RAW",
        auto_create_table=False,
    )

    n_staged = sum(1 for r in all_rows if r["STATUS"] == "staged")
    n_corrupt = len(all_rows) - n_staged
    LOG.info(
        "Done: %d staged, %d corrupt (of %d) across %d chunk(s)",
        n_staged,
        n_corrupt,
        len(all_rows),
        len(chunks),
    )

    if not keep_local:
        shutil.rmtree(WORKDIR, ignore_errors=True)
    return 0


@click.command()
@click.option("--config", default="conf/prepare.yaml", show_default=True)
@click.option("--limit", type=int, default=None, help="process at most N segments PER CHUNK")
@click.option("--dry-run", is_flag=True, help="download+unzip but skip staging/table writes")
@click.option(
    "--keep-local", is_flag=True, help="keep downloaded/unzipped files after each chunk"
)
@click.option(
    "--concurrency",
    type=int,
    default=DEFAULT_CONCURRENCY,
    show_default=True,
    help="threads used to stage segments within a chunk concurrently (each thread "
    "opens its own Snowpark session); pass 1 for strictly sequential staging",
)
def main(
    config: str, limit: int | None, dry_run: bool, keep_local: bool, concurrency: int
) -> None:
    """Phase 1: ingest comma2k19 chunk(s) into RAW_STAGE."""
    sys.exit(run(config, limit, dry_run, keep_local, concurrency))


if __name__ == "__main__":
    main()

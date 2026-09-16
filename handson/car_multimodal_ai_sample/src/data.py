"""Load Phase 3/5 Snowflake tables (SENSORS + SPLITS + FEATURES) into train/val/test
tensors.

Only the data *source* changed from the 45-minute handson's `src/data.py` (local
`features.npy` / `sensors.parquet` / `splits.json`) — the join/drop-invalid/scale
logic is the validated design and is NOT redesigned here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.utils import get_logger

LOG = get_logger("data")

DEFAULT_DATABASE = "CAR_MULTIMODAL_AI_DB"
DEFAULT_SCHEMA = "CURATED"


@dataclass
class Split:
    """One split's arrays, all row-aligned."""

    features: np.ndarray  # (n, 576) float32 image embeddings (Phase 5)
    sensors: np.ndarray  # (n, C) float32 ego-motion channels (scaled if requested)
    y: np.ndarray  # (n,) regression target (log-distance or distance)
    distance: np.ndarray  # (n,) raw lead distance [m]
    sample_ids: list[str]
    segments: np.ndarray


@dataclass
class Dataset:
    """The full dataset plus the transforms needed to interpret predictions."""

    train: Split
    val: Split
    test: Split
    sensor_channels: list[str]
    log_target: bool
    sensor_mean: np.ndarray
    sensor_std: np.ndarray

    def to_distance(self, y: np.ndarray) -> np.ndarray:
        """Map a model output back to metres."""
        return np.exp(y) if self.log_target else y


def _fqn(cfg: dict[str, Any], table: str) -> str:
    sf_cfg = cfg.get("snowflake", {})
    db = sf_cfg.get("database", DEFAULT_DATABASE)
    schema = sf_cfg.get("schema", DEFAULT_SCHEMA)
    return f"{db}.{schema}.{table}"


def load_dataset(session, cfg: dict[str, Any], limit: int | None = None) -> Dataset:
    """Assemble modelling arrays by joining SENSORS + SPLITS + FEATURES in Snowflake.

    Args:
        session: a live Snowpark session (`get_active_session()` inside a Notebook
            or ML Job; `Session.builder.configs(...).create()` elsewhere).
        cfg: parsed `conf/train.yaml` (must include `data.target`,
            `data.sensor_channels`, and optionally a `snowflake.{database,schema}`
            override).
        limit: optional row cap, mainly for `--dry-run` smoke tests (Phase 6).
    """
    sensors_fqn = _fqn(cfg, "SENSORS")
    features_fqn = _fqn(cfg, "FEATURES")
    splits_fqn = _fqn(cfg, "SPLITS")

    query = f"""
        SELECT s.SAMPLE_ID, s.SEGMENT, s.DISTANCE, s.REL_SPEED, s.SPEED,
               s.STEERING_ANGLE, s.WHEEL_SPEED_MEAN,
               s.ACCEL_X, s.ACCEL_Y, s.ACCEL_Z, s.GYRO_X, s.GYRO_Y, s.GYRO_Z,
               sp.SPLIT, f.EMBEDDING
        FROM {sensors_fqn} s
        JOIN {splits_fqn} sp ON sp.SEGMENT_ID = s.SEGMENT
        JOIN {features_fqn} f ON f.SAMPLE_ID = s.SAMPLE_ID
    """
    df = session.sql(query).to_pandas()
    if df.empty:
        raise ValueError(
            "Joined SENSORS/SPLITS/FEATURES returned 0 rows. "
            "Run Phase 2/3 (tables) and Phase 5 (embeddings) before training."
        )
    df.columns = [c.upper() for c in df.columns]

    target = cfg["data"]["target"].upper()
    channels = [c.upper() for c in cfg["data"]["sensor_channels"]]
    missing = [c for c in channels if c not in df.columns]
    if missing:
        raise ValueError(f"sensor_channels {missing} not in joined columns {list(df.columns)}")

    # Drop frames with no valid radar label or missing sensors (same rule as §3.3).
    valid = np.isfinite(df[target].to_numpy(dtype=float))
    for c in channels:
        valid &= np.isfinite(df[c].to_numpy(dtype=float))
    dropped = int((~valid).sum())
    df = df[valid].copy()
    if limit:
        df = df.iloc[:limit].copy()
    LOG.info(
        "Loaded %d samples (dropped %d invalid); %d segments",
        len(df),
        dropped,
        df["SEGMENT"].nunique(),
    )

    log_target = bool(cfg["data"].get("log_target", True))

    def _to_embedding(v) -> np.ndarray:
        # session.sql(...).to_pandas() returns ARRAY columns as JSON-formatted
        # strings (not native lists) — confirmed via real error
        # ("could not convert string to float: '[\n  1.98...,\n ...]'").
        if isinstance(v, str):
            v = json.loads(v)
        return np.asarray(v, dtype=np.float32)

    embeddings = np.stack(df["EMBEDDING"].apply(_to_embedding).to_numpy())

    def build(split_name: str) -> Split:
        mask = (df["SPLIT"] == split_name).to_numpy()
        sub = df[mask]
        dist = sub[target].to_numpy().astype(np.float32)
        y = np.log(dist) if log_target else dist
        return Split(
            features=embeddings[mask],
            sensors=sub[channels].to_numpy().astype(np.float32),
            y=y.astype(np.float32),
            distance=dist,
            sample_ids=sub["SAMPLE_ID"].tolist(),
            segments=sub["SEGMENT"].to_numpy(),
        )

    train, val, test = build("train"), build("val"), build("test")
    if len(train.y) == 0:
        raise ValueError("Empty train split. Check the SPLITS table and segment matching.")

    # StandardScaler on sensors, fit on train only (§4.2 of the 45-min AGENT.md).
    if bool(cfg["train"].get("normalize_sensors", True)):
        mean = train.sensors.mean(axis=0)
        std = train.sensors.std(axis=0)
        std[std < 1e-6] = 1.0
        for sp in (train, val, test):
            sp.sensors = ((sp.sensors - mean) / std).astype(np.float32)
    else:
        mean = np.zeros(len(channels), np.float32)
        std = np.ones(len(channels), np.float32)

    return Dataset(train, val, test, channels, log_target, mean, std)


def modality_inputs(split: Split, modality: str) -> dict[str, np.ndarray | None]:
    """Select which arrays a given modality feeds to the model."""
    if modality not in ("image", "sensor", "fusion"):
        raise ValueError(f"modality must be image|sensor|fusion, got {modality!r}")
    image = split.features if modality in ("image", "fusion") else None
    sensor = split.sensors if modality in ("sensor", "fusion") else None
    return {"image": image, "sensor": sensor}

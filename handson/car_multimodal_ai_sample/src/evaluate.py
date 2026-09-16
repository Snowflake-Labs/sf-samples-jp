"""Metrics and error analysis for a trained run.

Unchanged from the 45-minute handson (car_multimodal_handson/src/evaluate.py) —
pure numpy/pandas metric math with no Snowflake dependency. Reads a run's
predictions.parquet (written by src/train.py) and reports MAE / MAPE / R2, plus
the distance-banded MAE (near-range errors matter more than far-range) and the
mean-predictor baseline (R2<0 => worse than predicting the average => the model
learned nothing — this is what confirms the sensor-only arm "fails" in §3.3).

Phase 8's ML Job additionally logs these same metrics to ML Experiments /
Model Registry (see jobs/phase7_train_distributed.py) — this module is for
local/Notebook iteration (Phase 6) and quick sanity checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import numpy as np
import pandas as pd

from src.utils import get_logger, resolve

LOG = get_logger("evaluate")

DISTANCE_BANDS = [(0.0, 30.0), (30.0, 50.0), (50.0, np.inf)]


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs((y_true - y_pred) / y_true)) * 100.0)


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def banded_mae(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    out: dict[str, float] = {}
    for lo, hi in DISTANCE_BANDS:
        m = (y_true >= lo) & (y_true < hi)
        label = f"{int(lo)}-{'inf' if np.isinf(hi) else int(hi)}m"
        out[label] = mae(y_true[m], y_pred[m]) if m.any() else float("nan")
    return out


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Full metric bundle for one run, including the mean-predictor baseline."""
    baseline_pred = np.full_like(y_true, y_true.mean())
    return {
        "n": int(len(y_true)),
        "mae_m": round(mae(y_true, y_pred), 3),
        "mape_pct": round(mape(y_true, y_pred), 2),
        "r2": round(r2(y_true, y_pred), 4),
        "banded_mae_m": {k: round(v, 3) for k, v in banded_mae(y_true, y_pred).items()},
        "baseline_mae_m": round(mae(y_true, baseline_pred), 3),
        "baseline_r2": round(r2(y_true, baseline_pred), 4),
    }


def load_predictions(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "predictions.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No predictions in {run_dir}. Run `python -m src.train --modality <m>` first."
        )
    return pd.read_parquet(path)


def evaluate_run(run_dir: Path) -> dict:
    df = load_predictions(run_dir)
    metrics = compute_metrics(df["distance_true"].to_numpy(), df["distance_pred"].to_numpy())
    metrics["modality"] = run_dir.name
    return metrics


def _print_metrics(m: dict) -> None:
    LOG.info("── %s (n=%d) ─────────────────────", m.get("modality", "?"), m["n"])
    LOG.info("MAE   = %6.2f m   (baseline %.2f m)", m["mae_m"], m["baseline_mae_m"])
    LOG.info("MAPE  = %6.2f %%", m["mape_pct"])
    LOG.info("R2    = %6.3f     (baseline %.3f)", m["r2"], m["baseline_r2"])
    LOG.info("banded MAE: %s", "  ".join(f"{k}={v:.2f}" for k, v in m["banded_mae_m"].items()))
    if m["r2"] < 0:
        LOG.info("  -> R2 < 0: worse than predicting the mean. Model learned nothing (§3.3).")


def run(runs: tuple[str, ...], out: str, limit: int | None, dry_run: bool) -> int:
    runs = list(runs)[:limit] if limit else list(runs)
    all_metrics = []
    for run_path in runs:
        run_dir = resolve(run_path)
        if not (run_dir / "predictions.parquet").exists():
            LOG.warning("skip %s (no predictions)", run_dir)
            continue
        m = evaluate_run(run_dir)
        _print_metrics(m)
        all_metrics.append(m)

    if all_metrics and not dry_run:
        out_path = resolve(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_metrics, indent=2), encoding="utf-8")
        LOG.info("wrote %s", out_path)
    return 0


@click.command()
@click.option(
    "--runs",
    multiple=True,
    default=["runs/sensor", "runs/image", "runs/fusion"],
    show_default=True,
)
@click.option("--out", default="outputs/metrics.json", show_default=True)
@click.option("--limit", type=int, default=None, help="evaluate at most N runs")
@click.option("--dry-run", is_flag=True, help="print metrics but write no file")
def main(runs: tuple[str, ...], out: str, limit: int | None, dry_run: bool) -> None:
    """Evaluate one or more trained runs."""
    sys.exit(run(runs, out, limit, dry_run))


if __name__ == "__main__":
    main()

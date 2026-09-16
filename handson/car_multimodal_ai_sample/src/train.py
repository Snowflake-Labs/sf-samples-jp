"""Train the distance model for one modality.

    python -m src.train --modality sensor    # expected to underperform baseline (§3.3)
    python -m src.train --modality image     # expected to work
    python -m src.train --modality fusion    # expected ~= image, best near-range

Data is read from Snowflake tables (src/data.py) instead of local files — this is
the only change from the 45-minute handson's `src/train.py`. The training loop,
loss, and CLI shape are otherwise identical (validated design, §3.3/§4.2 of the
45-min AGENT.md).

Runs standalone in a Notebook (Phase 6, small `--max-samples` smoke test) or gets
imported by `jobs/phase7_train_distributed.py` as the `train_func` passed to
`PyTorchDistributor` for the full-scale run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click
import numpy as np
import torch
from torch import nn

from src.data import Dataset, Split, load_dataset, modality_inputs
from src.model import build_model
from src.utils import get_logger, load_config, resolve, set_seed, set_torch_threads

LOG = get_logger("train")


def _tensors(
    split: Split, modality: str
) -> tuple[torch.Tensor | None, torch.Tensor | None, torch.Tensor]:
    inp = modality_inputs(split, modality)
    image = None if inp["image"] is None else torch.from_numpy(inp["image"])
    sensor = None if inp["sensor"] is None else torch.from_numpy(inp["sensor"])
    y = torch.from_numpy(split.y)
    return image, sensor, y


def _iter_batches(n: int, batch_size: int, shuffle: bool, generator: torch.Generator):
    idx = torch.randperm(n, generator=generator) if shuffle else torch.arange(n)
    for start in range(0, n, batch_size):
        yield idx[start : start + batch_size]


def train_one_epoch(model, image, sensor, y, opt, loss_fn, batch_size, generator) -> float:
    """One pass over the training set (forward -> loss -> backward -> step)."""
    model.train()
    total = 0.0
    for batch in _iter_batches(len(y), batch_size, shuffle=True, generator=generator):
        img_b = None if image is None else image[batch]
        sen_b = None if sensor is None else sensor[batch]
        pred = model(image=img_b, sensor=sen_b)
        loss = loss_fn(pred, y[batch])
        opt.zero_grad()
        loss.backward()
        opt.step()
        total += loss.item() * len(batch)
    return total / len(y)


@torch.no_grad()
def evaluate_loss(model, image, sensor, y, loss_fn, batch_size) -> float:
    model.eval()
    total = 0.0
    for batch in _iter_batches(len(y), batch_size, shuffle=False, generator=None):
        img_b = None if image is None else image[batch]
        sen_b = None if sensor is None else sensor[batch]
        total += loss_fn(model(image=img_b, sensor=sen_b), y[batch]).item() * len(batch)
    return total / len(y)


@torch.no_grad()
def predict(model, split: Split, modality: str, ds: Dataset, batch_size: int) -> np.ndarray:
    model.eval()
    image, sensor, _ = _tensors(split, modality)
    preds = []
    for batch in _iter_batches(len(split.y), batch_size, shuffle=False, generator=None):
        img_b = None if image is None else image[batch]
        sen_b = None if sensor is None else sensor[batch]
        preds.append(model(image=img_b, sensor=sen_b).cpu().numpy())
    return ds.to_distance(np.concatenate(preds))


def make_loss(cfg: dict) -> nn.Module:
    name = cfg["train"]["loss"]
    if name == "huber":
        return nn.SmoothL1Loss(beta=float(cfg["train"]["huber_beta"]))
    if name == "mse":
        return nn.MSELoss()
    raise ValueError(f"Unknown loss {name!r}; use huber or mse.")


def run(
    session,
    cfg: dict,
    modality: str,
    out_dir: Path,
    dry_run: bool = False,
    max_samples: int | None = None,
) -> dict:
    """Train one modality end to end. Returns run metadata (also written to out_dir)."""
    out_dir = Path(out_dir)  # notebooks may pass a plain str (confirmed via real
    # AttributeError: 'str' object has no attribute 'mkdir'); Path objects pass through unchanged.
    set_seed(int(cfg["train"]["seed"]))
    set_torch_threads(int(cfg["train"]["torch_threads"]))
    ds = load_dataset(session, cfg, limit=max_samples)
    sensor_dim = len(ds.sensor_channels)
    model = build_model(modality, int(cfg["model"]["image_feat_dim"]), sensor_dim, cfg)
    n_params = sum(p.numel() for p in model.parameters())
    LOG.info(
        "modality=%s | train=%d val=%d test=%d | params=%d",
        modality,
        len(ds.train.y),
        len(ds.val.y),
        len(ds.test.y),
        n_params,
    )

    tr_img, tr_sen, tr_y = _tensors(ds.train, modality)
    va_img, va_sen, va_y = _tensors(ds.val, modality)
    loss_fn = make_loss(cfg)
    opt = torch.optim.Adam(
        model.parameters(),
        lr=float(cfg["train"]["lr"]),
        weight_decay=float(cfg["train"]["weight_decay"]),
    )
    gen = torch.Generator().manual_seed(int(cfg["train"]["seed"]))
    bs = int(cfg["train"]["batch_size"])
    epochs = int(cfg["train"]["epochs"])
    patience = int(cfg["train"]["early_stop_patience"])

    if dry_run:
        LOG.info("[dry-run] built model and data; skipping training.")
        return {"modality": modality, "dry_run": True}

    best_val = float("inf")
    best_state = None
    bad = 0
    t0 = time.time()
    for epoch in range(1, epochs + 1):
        tr_loss = train_one_epoch(model, tr_img, tr_sen, tr_y, opt, loss_fn, bs, gen)
        va_loss = evaluate_loss(model, va_img, va_sen, va_y, loss_fn, bs)
        LOG.info("epoch %2d/%d  train_loss=%.4f  val_loss=%.4f", epoch, epochs, tr_loss, va_loss)
        if va_loss < best_val - 1e-5:
            best_val, best_state, bad = (
                va_loss,
                {k: v.clone() for k, v in model.state_dict().items()},
                0,
            )
        else:
            bad += 1
            if bad >= patience:
                LOG.info("early stop at epoch %d (no val improvement for %d)", epoch, patience)
                break
    train_secs = time.time() - t0
    if best_state is not None:
        model.load_state_dict(best_state)
    LOG.info("trained in %.1fs (best val_loss=%.4f)", train_secs, best_val)

    import pandas as pd

    from src.evaluate import compute_metrics

    test_pred = predict(model, ds.test, modality, ds, bs)
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_df = pd.DataFrame(
        {
            "sample_id": ds.test.sample_ids,
            "segment": ds.test.segments,
            "distance_true": ds.test.distance,
            "distance_pred": test_pred,
        }
    )
    pred_df.to_parquet(out_dir / "predictions.parquet", index=False)
    torch.save(model.state_dict(), out_dir / "model.pt")
    # Compute metrics from the in-memory arrays directly, rather than reading
    # predictions.parquet back — an immediate re-read of a just-written parquet
    # file failed with "Parquet magic bytes not found" against the ML Job's
    # mounted filesystem (confirmed via real error). Callers that need metrics
    # (e.g. jobs/phase7_train_distributed.py logging to Experiments/Registry)
    # should use meta["metrics"] instead of round-tripping through the file.
    metrics = compute_metrics(ds.test.distance, test_pred)
    meta = {
        "modality": modality,
        "train_secs": round(train_secs, 1),
        "best_val_loss": round(best_val, 5),
        "n_params": n_params,
        "n_train": len(ds.train.y),
        "n_test": len(ds.test.y),
        "metrics": metrics,
    }
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    LOG.info("wrote predictions + model to %s", out_dir)
    return meta


@click.command()
@click.option("--config", default="conf/train.yaml", show_default=True)
@click.option(
    "--modality", type=click.Choice(["image", "sensor", "fusion"]), required=True
)
@click.option("--out", default=None, help="output dir (default runs/<modality>)")
@click.option("--limit", type=int, default=None, help="alias for --max-samples")
@click.option("--max-samples", type=int, default=None, help="subsample for a faster run")
@click.option("--dry-run", is_flag=True, help="build model/data, skip training")
def main(
    config: str,
    modality: str,
    out: str | None,
    limit: int | None,
    max_samples: int | None,
    dry_run: bool,
) -> None:
    """Train the distance model for one modality."""
    from snowflake.snowpark.context import get_active_session

    session = get_active_session()
    cfg = load_config(config)
    out_dir = resolve(out) if out else resolve("runs") / modality
    max_samples = max_samples or limit
    run(session, cfg, modality, out_dir, dry_run=dry_run, max_samples=max_samples)
    sys.exit(0)


if __name__ == "__main__":
    main()

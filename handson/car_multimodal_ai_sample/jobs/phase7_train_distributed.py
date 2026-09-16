"""Phase 7 — distributed training via ML Jobs, + Phase 8 — record to ML Experiments
and Model Registry.

Trains all three ablation conditions (sensor / image / fusion) at full Chunk_1
scale using `PyTorchDistributor`, logs each run's metrics/params to
`snowflake.ml.experiment.ExperimentTracking`, and registers each trained model
in the Model Registry — so Streamlit (Phase 8) can trace a displayed metric
back to a specific model version.

Default is real multi-node training: 4 nodes (`conf/train.yaml:
distributed.num_nodes`, overridable via `--nodes N`/`scripts/submit_phase7.py
--nodes N`). With `num_nodes > 1`, each modality trains with real
`torch.distributed` DDP: every worker builds its own Snowpark session
(`get_active_session()`/closures don't survive across worker processes — the
same fix Phase 2 needed), shards the training set by rank, and rank 0 alone
saves the model/metrics. Multi-node model artifacts must land on a stage
(`CURATED.JOB_STAGE`), not local disk, since workers on different nodes don't
share a filesystem with the driver. Pass `--nodes 1` for a single-node smoke
test that skips `PyTorchDistributor`/DDP entirely (this data volume, ~22.5k
samples, doesn't need 4 nodes for speed alone — 4 is the default specifically
so this phase demonstrates actual distributed training out of the box).

Usage:

    python jobs/phase7_train_distributed.py --dry-run --max-samples 500
    python jobs/phase7_train_distributed.py                          # default: real DDP across 4 nodes
    python jobs/phase7_train_distributed.py --modality fusion         # one modality only
    python jobs/phase7_train_distributed.py --nodes 1                 # single-node smoke test (no DDP)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.train import run as train_run  # noqa: E402
from src.utils import get_logger, load_config, resolve  # noqa: E402

LOG = get_logger("phase7_train_distributed")

MODALITIES = ["sensor", "image", "fusion"]
MODEL_ARTIFACT_STAGE = "CAR_MULTIMODAL_AI_DB.CURATED.JOB_STAGE"


def train_one_modality_distributed(session, cfg: dict, modality: str, out_dir, max_samples=None):
    """Single-node training path: run src.train.run() directly in the driver process."""
    return train_run(session, cfg, modality, out_dir, dry_run=False, max_samples=max_samples)


def _ddp_train_worker(cfg: dict, modality: str, max_samples: int | None, run_stage_dir: str) -> None:
    """PyTorchDistributor `train_func` for `num_nodes > 1` — runs on every worker
    process across every node.

    Builds its own Snowpark session (a session captured in a closure can't be
    shared across worker processes — confirmed via the same `SnowparkSessionException:
    No default Session is found` error Phase 2 hit), shards the already-loaded
    training set by rank (each rank trains on a disjoint slice; DDP all-reduces
    gradients every `backward()` so all ranks' models stay in sync regardless),
    and — rank 0 only — evaluates on the test split and PUTs the model +
    metrics to `run_stage_dir` on `MODEL_ARTIFACT_STAGE` itself (not via
    `context.get_model_dir()`/`artifact_stage_location` — confirmed via a real
    deprecation warning that that mechanism's local scratch dir is "not
    uploaded" by the framework at all).
    """
    import torch
    import torch.distributed as dist
    from snowflake.ml.modeling.distributors.pytorch import get_context
    from snowflake.ml.utils.connection_params import SnowflakeLoginOptions
    from snowflake.snowpark import Session
    from torch.nn.parallel import DistributedDataParallel as DDP

    from src.data import load_dataset
    from src.evaluate import compute_metrics
    from src.model import build_model
    from src.train import _tensors, evaluate_loss, make_loss, predict, train_one_epoch
    from src.utils import set_seed, set_torch_threads

    log = get_logger(f"phase7_ddp_{modality}")
    context = get_context()
    # PyTorchDistributor already calls dist.init_process_group() around
    # train_func for every worker (confirmed via real error: calling it again
    # here raised "trying to initialize the default process group twice!") —
    # just read the already-initialized process group's rank/world size.
    rank = context.get_world_rank()
    world_size = dist.get_world_size()
    log.info("worker started: rank=%d/%d modality=%s", rank, world_size, modality)

    session = Session.builder.configs(SnowflakeLoginOptions()).create()
    try:
        set_seed(int(cfg["train"]["seed"]))
        set_torch_threads(int(cfg["train"]["torch_threads"]))
        ds = load_dataset(session, cfg, limit=max_samples)

        sensor_dim = len(ds.sensor_channels)
        model = build_model(modality, int(cfg["model"]["image_feat_dim"]), sensor_dim, cfg)
        model = DDP(model)

        tr_img, tr_sen, tr_y = _tensors(ds.train, modality)
        va_img, va_sen, va_y = _tensors(ds.val, modality)

        # Disjoint shard per rank; DDP handles gradient sync, so no explicit
        # all-reduce/broadcast is needed here for correctness.
        n = len(tr_y)
        shard_idx = torch.arange(rank, n, world_size)
        tr_img_r = None if tr_img is None else tr_img[shard_idx]
        tr_sen_r = None if tr_sen is None else tr_sen[shard_idx]
        tr_y_r = tr_y[shard_idx]

        loss_fn = make_loss(cfg)
        opt = torch.optim.Adam(
            model.parameters(),
            lr=float(cfg["train"]["lr"]),
            weight_decay=float(cfg["train"]["weight_decay"]),
        )
        gen = torch.Generator().manual_seed(int(cfg["train"]["seed"]) + rank)
        bs = max(1, int(cfg["train"]["batch_size"]) // world_size)
        epochs = int(cfg["train"]["epochs"])
        patience = int(cfg["train"]["early_stop_patience"])

        best_val = float("inf")
        best_state = None
        bad = 0
        t0 = time.time()
        for epoch in range(1, epochs + 1):
            tr_loss = train_one_epoch(model, tr_img_r, tr_sen_r, tr_y_r, opt, loss_fn, bs, gen)
            # Every rank has the full val split and an identical (DDP-synced)
            # model, so every rank reaches the same early-stop decision without
            # needing to broadcast it.
            va_loss = evaluate_loss(model, va_img, va_sen, va_y, loss_fn, bs)
            if rank == 0:
                log.info("epoch %2d/%d  train_loss=%.4f  val_loss=%.4f", epoch, epochs, tr_loss, va_loss)
            if va_loss < best_val - 1e-5:
                best_val, best_state, bad = (
                    va_loss,
                    {k: v.clone() for k, v in model.state_dict().items()},
                    0,
                )
            else:
                bad += 1
                if bad >= patience:
                    if rank == 0:
                        log.info("early stop at epoch %d", epoch)
                    break
        train_secs = time.time() - t0
        if best_state is not None:
            model.load_state_dict(best_state)

        if rank != 0:
            return

        import pandas as pd

        test_pred = predict(model.module, ds.test, modality, ds, bs)
        metrics = compute_metrics(ds.test.distance, test_pred)

        local_dir = Path(f"/tmp/phase7_ddp_{modality}")
        local_dir.mkdir(parents=True, exist_ok=True)
        torch.save(model.module.state_dict(), local_dir / "model.pt")
        pred_df = pd.DataFrame(
            {
                "sample_id": ds.test.sample_ids,
                "segment": ds.test.segments,
                "distance_true": ds.test.distance,
                "distance_pred": test_pred,
            }
        )
        pred_df.to_parquet(local_dir / "predictions.parquet", index=False)
        meta = {
            "modality": modality,
            "train_secs": round(train_secs, 1),
            "best_val_loss": round(best_val, 5),
            "n_train": int(n),
            "n_test": len(ds.test.y),
            "metrics": metrics,
            "world_size": world_size,
        }
        (local_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        log.info("rank 0 PUTting artifacts to @%s/%s/", MODEL_ARTIFACT_STAGE, run_stage_dir)
        session.file.put(
            str(local_dir / "*"),
            f"@{MODEL_ARTIFACT_STAGE}/{run_stage_dir}/",
            auto_compress=False,
            overwrite=True,
        )
    finally:
        session.close()


def train_via_distributor(session, cfg: dict, modality: str, out_dir, max_samples=None) -> dict:
    """Single-node: run directly (no Ray/DDP orchestration overhead needed at this
    data volume). `num_nodes > 1`: real DDP training via PyTorchDistributor,
    with model artifacts round-tripped through `MODEL_ARTIFACT_STAGE` since
    worker nodes don't share a filesystem with the driver."""
    dist_cfg = cfg.get("distributed", {})
    num_nodes = int(dist_cfg.get("num_nodes", 1))

    if num_nodes <= 1:
        return train_one_modality_distributed(session, cfg, modality, out_dir, max_samples)

    from snowflake.ml.modeling.distributors.pytorch import (
        PyTorchDistributor,
        PyTorchScalingConfig,
        WorkerResourceConfig,
    )

    run_stage_dir = f"phase7_ddp/{modality}_{int(time.time())}"
    distributor = PyTorchDistributor(
        train_func=lambda: _ddp_train_worker(cfg, modality, max_samples, run_stage_dir),
        scaling_config=PyTorchScalingConfig(
            num_nodes=num_nodes,
            num_workers_per_node=int(dist_cfg.get("num_workers_per_node", 1)),
            resource_requirements_per_worker=WorkerResourceConfig(
                num_cpus=int(dist_cfg.get("num_cpus_per_worker", 2))
            ),
        ),
    )
    distributor.run()

    # rank 0 PUT its artifacts to @MODEL_ARTIFACT_STAGE/run_stage_dir/ itself
    # (see _ddp_train_worker) — GET them back to `out_dir` so
    # log_experiment_and_register() below can read them exactly like the
    # single-node path. A trailing "/*" glob on GET raised "the file does not
    # exist" even though LIST confirmed the files were there (confirmed via a
    # real, reproduced-locally error) — GET wants a trailing "/" instead.
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session.file.get(f"@{MODEL_ARTIFACT_STAGE}/{run_stage_dir}/", str(out_dir))
    return json.loads((out_dir / "run_meta.json").read_text())


def log_experiment_and_register(session, cfg: dict, modality: str, out_dir, meta: dict) -> None:
    """Phase 8: log the run to ML Experiments and register the model in Model Registry."""
    import torch

    from src.data import load_dataset
    from src.model import RegistryInferenceWrapper, build_model

    # meta["metrics"] is computed in-memory by src.train.run() — avoid re-reading
    # predictions.parquet here (an immediate re-read of a just-written parquet
    # file failed with "Parquet magic bytes not found" against the ML Job's
    # mounted filesystem; confirmed via real error).
    metrics = meta.get("metrics")
    if not metrics:
        LOG.warning("no metrics in run meta for modality=%s; skipping experiment/registry logging", modality)
        return

    from snowflake.ml.experiment import ExperimentTracking

    db = cfg["snowflake"]["database"]
    exp = ExperimentTracking(session=session, database_name=db, schema_name="ML")
    exp.set_experiment("lead_distance_estimation")
    with exp.start_run(run_name=f"{modality}_{int(time.time())}"):
        exp.log_param("modality", modality)
        exp.log_param("sensor_channels", cfg["data"]["sensor_channels"])
        exp.log_metric("test_mae_m", metrics["mae_m"])
        exp.log_metric("test_r2", metrics["r2"])
        exp.log_metric("test_mape_pct", metrics["mape_pct"])
        exp.log_metric("baseline_mae_m", metrics["baseline_mae_m"])
        for band, val in metrics["banded_mae_m"].items():
            exp.log_metric(f"mae_{band}", val)
        exp.log_metric("train_secs", meta.get("train_secs", 0.0))

    from snowflake.ml.registry import Registry

    # Workaround: snowflake.ml.model.event_handler.ModelEventHandler.__init__ does
    # `import streamlit as st; if st.runtime.exists(): ...` but only catches
    # ImportError — not the AttributeError this Container Runtime's streamlit
    # build raises (it imports fine but has no `runtime` attribute). Confirmed
    # via real error: `AttributeError: module 'streamlit' has no attribute
    # 'runtime'` inside `Registry.log_model()`. Forcing the internal import to
    # fail with ImportError (by shadowing the module) makes it fall back to
    # tqdm-only progress reporting, which is all this batch job needs anyway.
    import sys

    sys.modules["streamlit"] = None  # type: ignore[assignment]

    # No `limit=` here: a small limit can pull rows from only train/val segments,
    # leaving ds.test empty (confirmed via real error — "IndexError: index 0 is
    # out of bounds for axis 0 with size 0" from an empty sample_input array).
    ds = load_dataset(session, cfg)
    sensor_dim = len(ds.sensor_channels)
    image_dim = int(cfg["model"]["image_feat_dim"])
    model = build_model(modality, image_dim, sensor_dim, cfg)
    model.load_state_dict(torch.load(out_dir / "model.pt", map_location="cpu"))
    model.eval()
    registry_model = RegistryInferenceWrapper(model, image_dim, sensor_dim)

    # Single-tensor sample input matching RegistryInferenceWrapper.forward()'s
    # signature: image-dim columns, sensor-dim columns,
    # or both concatenated for fusion.
    import numpy as np

    n = 4
    if modality == "image":
        sample_input = ds.test.features[:n].astype(np.float32)
    elif modality == "sensor":
        sample_input = ds.test.sensors[:n].astype(np.float32)
    else:
        sample_input = np.concatenate(
            [ds.test.features[:n], ds.test.sensors[:n]], axis=1
        ).astype(np.float32)

    reg = Registry(session=session, database_name=db, schema_name="ML")
    reg.log_model(
        model=registry_model,
        model_name=f"LEAD_DISTANCE_{modality.upper()}",
        version_name=f"v_{int(time.time())}",
        sample_input_data=sample_input,
        metrics={"mae_m": metrics["mae_m"], "r2": metrics["r2"]},
        comment=f"Radar-supervised {modality} model (comma2k19 Chunk_1)",
    )
    LOG.info("Logged experiment + registered model for modality=%s", modality)


def run(config: str, modality: str | None, max_samples: int | None, dry_run: bool, nodes: int | None) -> int:
    cfg = load_config(resolve(config))
    if nodes is not None:
        cfg.setdefault("distributed", {})["num_nodes"] = nodes
    modalities = [modality] if modality else MODALITIES

    from snowflake.snowpark.context import get_active_session

    session = get_active_session()

    all_metrics = []
    for m in modalities:
        out_dir = resolve("runs") / m
        LOG.info("=== training modality=%s ===", m)
        if dry_run:
            train_one_modality_distributed(session, cfg, m, out_dir, max_samples=max_samples)
            continue
        meta = train_via_distributor(session, cfg, m, out_dir, max_samples=max_samples)
        log_experiment_and_register(session, cfg, m, out_dir, meta)
        all_metrics.append({"modality": m, **meta})

    if not dry_run:
        LOG.info("=== summary ===")
        for entry in all_metrics:
            LOG.info("%s: %s", entry["modality"], entry)
    return 0


@click.command()
@click.option("--config", default="conf/train.yaml", show_default=True)
@click.option(
    "--modality",
    type=click.Choice(MODALITIES),
    default=None,
    help="train one modality only",
)
@click.option("--max-samples", type=int, default=None, help="subsample for a faster run")
@click.option("--dry-run", is_flag=True, help="build model/data, skip training+logging")
@click.option(
    "--nodes",
    type=int,
    default=None,
    help="override conf/train.yaml: distributed.num_nodes for this run "
    "(>1 trains with real torch.distributed DDP across that many nodes)",
)
def main(config: str, modality: str | None, max_samples: int | None, dry_run: bool, nodes: int | None) -> None:
    """Phase 7/8: distributed training + experiment/registry."""
    sys.exit(run(config, modality, max_samples, dry_run, nodes))


if __name__ == "__main__":
    main()

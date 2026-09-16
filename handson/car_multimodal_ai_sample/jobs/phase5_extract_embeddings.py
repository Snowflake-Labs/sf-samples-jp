"""Phase 5 — extract 576-dim frozen-backbone embeddings from `@IMAGES_STAGE/cropped/`
and register them in the `FEATURES` table.

Uses the Snowflake ML DataSource API (Ray Data) to read images directly from the
stage in parallel, and a DataSink to write the resulting embeddings back to a
table — no local file round-trip. `ray.data.read_datasource()`/`.map_batches()`
already spread work across every node in the Ray cluster the job lands on, so no
job-script change is needed for multi-node — this script never even checks how
many nodes it has; whatever `--nodes N` was passed to `scripts/submit_phase5.py`
(mapped to `submit_directory(..., target_instances=N)`) determines the Ray
cluster size, and `ray.init(address="auto")` just joins whatever cluster is
already there. **Default is 4 nodes** (`scripts/submit_phase5.py --nodes 4` is
the default, not opt-in), so running this phase with no flags demonstrates real
multi-node distribution out of the box — this data volume (22,504 images) doesn't
strictly need 4 nodes for speed (a single node extracts it in a few minutes), but
4 is the default specifically so "distributed" isn't just a name. Pass `--nodes 1`
for a single-node run.

Usage:

    python jobs/phase5_extract_embeddings.py --dry-run --limit 50
    python jobs/phase5_extract_embeddings.py                      # full IMAGES_STAGE
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils import get_logger, load_config, resolve  # noqa: E402

LOG = get_logger("phase5_extract_embeddings")

# comma2k19 crop is applied before the backbone; must match Phase 2/conf/prepare.yaml.
_SAMPLE_ID_RE = re.compile(r"([^/]+)\.jpg$")


def build_extractor(input_size: int):
    """Frozen MobileNetV3-small trunk -> 576-d feature."""
    import torch
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
    model = mobilenet_v3_small(weights=weights)
    model.classifier = torch.nn.Identity()  # keep features+avgpool -> 576
    model.eval()
    transform = weights.transforms()
    return model, transform


def extract_embedding_batch(batch: dict, input_size: int, model_name: str, generated_at) -> dict:
    """Ray Data map_batches function: images -> 576-d embeddings (called per worker)."""
    import numpy as np
    import torch
    from PIL import Image

    model, transform = build_extractor(input_size)
    images = batch["image"]  # list/array of HxWx3 uint8 arrays (SFStageImageDataSource)
    paths = batch["path"]

    imgs = [Image.fromarray(im) for im in images]
    tensor = torch.stack([transform(im) for im in imgs])
    with torch.no_grad():
        feats = model(tensor).cpu().numpy().astype(np.float32)

    sample_ids = []
    for p in paths:
        m = _SAMPLE_ID_RE.search(str(p))
        sample_ids.append(m.group(1) if m else str(p))

    n = len(sample_ids)
    return {
        "SAMPLE_ID": np.asarray(sample_ids, dtype=object),
        "EMBEDDING": [row.tolist() for row in feats],
        # Provenance columns: which frozen backbone produced this
        # embedding, and when this Phase 5 run generated it. All rows from a
        # single run share the same GENERATED_AT (passed down from main(), not
        # recomputed per-batch) so a run's embeddings are trivially groupable.
        # `generated_at` must be a real datetime64 (not a string) here — passing
        # a plain str made SnowflakeTableDatasink infer a VARCHAR column instead
        # of TIMESTAMP_NTZ (confirmed via real `DESCRIBE TABLE`).
        "MODEL_NAME": np.full(n, model_name, dtype=object),
        "GENERATED_AT": np.full(n, generated_at, dtype="datetime64[us]"),
    }


def run(config: str, limit: int | None, dry_run: bool) -> int:
    cfg = load_config(resolve(config))
    images_stage = cfg["snowflake"]["stages"]["images"]
    # SFStageImageDataSource further-qualifies stage_location with the session's
    # current database/schema; passing an already-fully-qualified name produces a
    # duplicated identifier like "DB"."SCHEMA".DB.SCHEMA.STAGE (confirmed via real error). The ML Job
    # session's database/schema is already set to this stage's location
    # (scripts/_submit_common.py), so pass only the bare stage name here.
    bare_images_stage = "@" + images_stage.rsplit(".", 1)[-1].lstrip("@")
    input_size = int(cfg["features"]["input_size"])
    model_name = cfg["features"]["backbone"]
    # One timestamp for the whole run (not per-batch/per-row) so every row
    # written by this Phase 5 execution is trivially groupable by run.
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    import ray
    from snowflake.ml.ray.datasink import SnowflakeTableDatasink
    from snowflake.ml.ray.datasource.stage_image_datasource import SFStageImageDataSource

    if not ray.is_initialized():
        ray.init(address="auto", ignore_reinit_error=True)
    LOG.info("Ray cluster: %d node(s) available", len(ray.nodes()))

    image_source = SFStageImageDataSource(
        stage_location=f"{bare_images_stage}/cropped/",
        file_pattern="*.jpg",
        # Without this, batches only have an "image" column — no filename to
        # derive sample_id from (confirmed via real schema inspection: default
        # schema is image-only, "path" only appears with include_paths=True).
        include_paths=True,
    )
    ray_ds = ray.data.read_datasource(image_source)
    if limit:
        ray_ds = ray_ds.limit(limit)

    n_images = ray_ds.count()
    LOG.info(
        "Extracting embeddings for %d images from %s/cropped/ (model=%s, generated_at=%s)",
        n_images,
        images_stage,
        model_name,
        generated_at,
    )

    embedded_ds = ray_ds.map_batches(
        extract_embedding_batch,
        fn_kwargs={"input_size": input_size, "model_name": model_name, "generated_at": generated_at},
        batch_format="pandas",
    )

    if dry_run:
        sample = embedded_ds.take(3)
        for row in sample:
            LOG.info(
                "[dry-run] sample_id=%s embedding_dim=%d model_name=%s generated_at=%s",
                row["SAMPLE_ID"],
                len(row["EMBEDDING"]),
                row["MODEL_NAME"],
                row["GENERATED_AT"],
            )
        LOG.info("[dry-run] skipping FEATURES table write")
        return 0

    datasink = SnowflakeTableDatasink(
        table_name="FEATURES",
        database=cfg["snowflake"]["database"],
        schema="CURATED",
        auto_create_table=True,
        override=True,
    )
    embedded_ds.write_datasink(datasink)

    # SnowflakeTableDatasink's pyarrow-based auto_create_table infers a plain
    # NUMBER(38,0) (raw epoch microseconds) for a numpy datetime64 column
    # instead of TIMESTAMP_NTZ (confirmed via real `DESCRIBE TABLE` — this is
    # an snowflake-ml-python type-inference limitation, not fixable from the
    # numpy/pandas side). Cast it in place with a single atomic CTAS, which is
    # consistent with the override=True (full-replace) semantics already used
    # above.
    from snowflake.snowpark.context import get_active_session

    session = get_active_session()
    full_table = f"{cfg['snowflake']['database']}.CURATED.FEATURES"
    session.sql(
        f"""
        CREATE OR REPLACE TABLE {full_table} AS
        SELECT SAMPLE_ID, EMBEDDING, MODEL_NAME,
               TO_TIMESTAMP_NTZ(GENERATED_AT, 6) AS GENERATED_AT
        FROM {full_table}
        """
    ).collect()
    LOG.info("Cast GENERATED_AT to TIMESTAMP_NTZ in %s", full_table)

    LOG.info(
        "Wrote %d embeddings to CURATED.FEATURES (dim=%d, model=%s, generated_at=%s)",
        n_images,
        int(cfg["features"]["dim"]),
        model_name,
        generated_at,
    )
    return 0


@click.command()
@click.option("--config", default="conf/prepare.yaml", show_default=True)
@click.option("--limit", type=int, default=None, help="process at most N images")
@click.option("--dry-run", is_flag=True, help="run extraction but skip table write")
def main(config: str, limit: int | None, dry_run: bool) -> None:
    """Phase 5: extract image embeddings to FEATURES."""
    sys.exit(run(config, limit, dry_run))


if __name__ == "__main__":
    main()

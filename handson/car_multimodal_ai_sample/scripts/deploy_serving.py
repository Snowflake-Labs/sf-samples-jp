"""Phase 9 — deploy the Phase 7 trained models as online inference services on
Snowpark Container Services.

Takes each registered model version (`ML.LEAD_DISTANCE_{SENSOR,IMAGE,FUSION}`,
written by Phase 7) and calls `ModelVersion.create_service()` to host it as a
long-running HTTP inference server inside SPCS, so a request/response app
(`streamlit/inference_app.py`, Phase 9's UI) can get a single-sample prediction in
milliseconds instead of running a batch job.

Why a local control-plane script and not an ML Job (like Phase 1/2/5/7 are):
`create_service()` does no local compute — it asks Snowflake to build a container
image for the model version and start a service from it, then returns. Running it
inside an ML Job would just park a job container idle for the ~10 minutes the
server-side image build takes. This mirrors `scripts/deploy_streamlit.py`, which
is also a control-plane-only step.

Services are created with `ingress_enabled=False`: the only client in this sample
is Streamlit-in-Snowflake, which calls the service from *inside* Snowflake (SQL
service function / `ModelVersion.run(..., service_name=...)`), so no public
endpoint — and no PAT handling or `BIND SERVICE ENDPOINT` privilege — is needed.
Pass `--ingress` to additionally expose a public HTTPS endpoint.

Usage (run from the project root):

    export SNOWFLAKE_CONNECTION_NAME=<your-connection>
    python3 scripts/deploy_serving.py --dry-run     # resolve versions, print the plan
    python3 scripts/deploy_serving.py                # deploy all 3 modalities
    python3 scripts/deploy_serving.py --modality fusion
    python3 scripts/deploy_serving.py --recreate      # drop + redeploy (e.g. after retraining)
    python3 scripts/deploy_serving.py --drop          # remove the services only
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from snowpark_session import create_snowpark_session  # noqa: E402
from src.serving import (  # noqa: E402
    MODALITIES,
    build_payload,
    model_name_for,
    resolve_function_name,
    service_name_for,
    to_distance,
)

DATABASE = "CAR_MULTIMODAL_AI_DB"
ML_SCHEMA = "ML"
SERVING_POOL = "MULTIMODAL_SERVING_POOL"
# Image builds don't need the serving pool's shape; reuse the (larger) ML-Jobs pool
# so the serving pool doesn't have to scale up just to compile an image.
IMAGE_BUILD_POOL = "MULTIMODAL_CPU_POOL"

# Poll budget for the service to report READY. A first-time CPU image build is
# documented at up to ~10 min per model; 30 min gives headroom for a cold pool.
READY_TIMEOUT_S = 1800
POLL_INTERVAL_S = 20


def resolve_latest_version(registry, modality: str):
    """The most recently created version of this modality's registered model.

    Phase 7 versions models as `v_<unix_ts>` (one per training run), so "latest"
    is what a redeploy after retraining should pick up. `Model.last()` is not
    relied on here — `show_versions()` ordering is explicit and inspectable.
    """
    model = registry.get_model(model_name_for(modality))
    versions = model.show_versions()
    if versions.empty:
        raise RuntimeError(
            f"{model_name_for(modality)} has no versions. Run Phase 7 "
            "(scripts/submit_phase7.py) before deploying serving."
        )
    latest = versions.sort_values("created_on").iloc[-1]["name"]
    return model.version(latest)


def service_status(session, service: str) -> str | None:
    """Current status of a service, or None if it doesn't exist yet."""
    rows = session.sql(
        f"SHOW SERVICES LIKE '{service}' IN SCHEMA {DATABASE}.{ML_SCHEMA}"
    ).collect()
    if not rows:
        return None
    row = rows[0].as_dict()
    # Column name has varied across versions ("status" vs "state").
    return row.get("status") or row.get("state")


def wait_until_ready(session, service: str) -> str:
    """Block until the service reports RUNNING/READY (or raise on failure/timeout)."""
    deadline = time.time() + READY_TIMEOUT_S
    last = None
    while time.time() < deadline:
        status = (service_status(session, service) or "UNKNOWN").upper()
        if status != last:
            print(f"  [{service}] status={status}")
            last = status
        if status in ("RUNNING", "READY"):
            return status
        if status in ("FAILED", "INTERNAL_ERROR", "DELETING", "DELETED"):
            raise RuntimeError(f"service {service} entered terminal status {status}")
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"service {service} did not become ready within {READY_TIMEOUT_S}s "
        f"(last status={last}). Check: SHOW SERVICE CONTAINERS IN SERVICE "
        f"{DATABASE}.{ML_SCHEMA}.{service};"
    )


def load_smoke_test_data(session):
    """Load the dataset once, for reuse across every modality's smoke test.

    `load_dataset()` pulls the whole SENSORS ⋈ SPLITS ⋈ FEATURES join (~22.5k rows ×
    583 floats) — worth doing exactly once per run, not once per modality.
    """
    from src.data import load_dataset
    from src.utils import load_config

    cfg = load_config(str(Path(__file__).resolve().parent.parent / "conf" / "train.yaml"))
    return cfg, load_dataset(session, cfg)


def smoke_test(cfg, ds, mv, modality: str, service: str) -> None:
    """Send real requests through the service and print predictions vs. ground truth.

    Cross-checks the deployed service against the same `src/data.py` pipeline that
    trained it: same standardised sensors, same single-tensor layout
    (`src/serving.build_payload`), same log-distance inversion. If the numbers here
    look nothing like the radar column, the serving input contract is wrong — not
    the model.
    """
    import numpy as np

    n = 3
    image_dim = int(cfg["model"]["image_feat_dim"])
    batch = np.concatenate(
        [
            build_payload(modality, ds.test.features[i], ds.test.sensors[i], image_dim=image_dim)
            for i in range(n)
        ],
        axis=0,
    )

    t0 = time.time()
    function_name = resolve_function_name(mv.show_functions())
    out = mv.run(
        batch,
        function_name=function_name,
        service_name=f"{DATABASE}.{ML_SCHEMA}.{service}",
    )
    elapsed_ms = 1000 * (time.time() - t0)

    preds = np.asarray(out).reshape(-1)
    distances = to_distance(preds, log_target=bool(cfg["data"].get("log_target", True)))
    truth = ds.test.distance[:n]
    print(f"  [{service}] {function_name}() round-trip {elapsed_ms:.0f} ms for {n} rows")
    for pred_m, true_m in zip(distances, truth, strict=True):
        print(f"    predicted {pred_m:6.2f} m   radar ground truth {true_m:6.2f} m")


def drop_service(session, service: str) -> None:
    print(f"=== Dropping service {service} ===")
    session.sql(f"DROP SERVICE IF EXISTS {DATABASE}.{ML_SCHEMA}.{service}").collect()
    print(f"  dropped {service}")


def deploy_one(
    session, registry, modality: str, ingress: bool, recreate: bool, build_eai: str | None
) -> tuple:
    """Create (if needed) and confirm one modality's service. Returns (mv, service)."""
    service = service_name_for(modality)
    mv = resolve_latest_version(registry, modality)
    print(f"=== {modality}: {model_name_for(modality)} version {mv.version_name} -> {service} ===")

    existing = service_status(session, service)
    if existing and recreate:
        drop_service(session, service)
        existing = None
    elif existing:
        print(f"  service already exists (status={existing}); skipping create "
              "(pass --recreate to replace it)")

    if not existing:
        print(f"  creating service on {SERVING_POOL} (image build ~10 min on first deploy)...")
        kwargs = {}
        if build_eai:
            # Only needed if the image build can't reach its package index on its own.
            # Snowflake normally resolves the model's conda deps from conda-forge without
            # any account-level EAI, so this stays opt-in rather than always-on.
            kwargs["build_external_access_integrations"] = [build_eai]
        mv.create_service(
            service_name=f"{DATABASE}.{ML_SCHEMA}.{service}",
            service_compute_pool=SERVING_POOL,
            image_build_compute_pool=IMAGE_BUILD_POOL,
            ingress_enabled=ingress,
            gpu_requests=None,  # these models are tiny MLPs; CPU is plenty
            max_instances=1,
            # block=True (the default) already waits for the build + rollout; the
            # wait_until_ready() call below is an independent status confirmation.
            **kwargs,
        )

    wait_until_ready(session, service)
    return mv, service


@click.command()
@click.option(
    "--modality",
    type=click.Choice(list(MODALITIES)),
    default=None,
    help="deploy one modality only (default: all three)",
)
@click.option("--ingress", is_flag=True, help="also expose a public HTTPS endpoint (needs BIND SERVICE ENDPOINT)")
@click.option("--recreate", is_flag=True, help="drop and recreate services that already exist")
@click.option("--drop", "drop_only", is_flag=True, help="drop the services and exit")
@click.option(
    "--build-eai",
    default=None,
    help="external access integration for the image build, if it can't reach its "
    "package index (e.g. PYPI_ACCESS_INTEGRATION)",
)
@click.option("--dry-run", is_flag=True, help="resolve model versions and print the plan, create nothing")
def main(
    modality: str | None,
    ingress: bool,
    recreate: bool,
    drop_only: bool,
    build_eai: str | None,
    dry_run: bool,
) -> None:
    """Phase 9: deploy trained models as SPCS online inference services."""
    from snowflake.ml.registry import Registry

    modalities = [modality] if modality else MODALITIES
    session = create_snowpark_session()
    try:
        session.use_database(DATABASE)
        session.use_schema(ML_SCHEMA)

        if drop_only:
            for m in modalities:
                drop_service(session, service_name_for(m))
            print("\nServices dropped. The serving compute pool is left in place "
                  "(it auto-suspends once idle).")
            return

        registry = Registry(session=session, database_name=DATABASE, schema_name=ML_SCHEMA)

        if dry_run:
            for m in modalities:
                mv = resolve_latest_version(registry, m)
                status = service_status(session, service_name_for(m))
                print(f"[dry-run] {m}: {model_name_for(m)} version {mv.version_name} "
                      f"-> {service_name_for(m)} on {SERVING_POOL} "
                      f"(existing status: {status or 'not deployed'})")
            print("[dry-run] no services created")
            return

        deployed_services = [
            deploy_one(session, registry, m, ingress, recreate, build_eai) for m in modalities
        ]

        # Smoke-test only after every service is up, so one shared dataset load
        # covers all of them.
        print("\n=== Smoke test (service prediction vs. radar ground truth) ===")
        cfg, ds = load_smoke_test_data(session)
        for (mv, service), m in zip(deployed_services, modalities, strict=True):
            smoke_test(cfg, ds, mv, m, service)

        print("\n=== Deployed services ===")
        rows = session.sql(
            f"SHOW SERVICES LIKE 'LEAD_DISTANCE_%_SVC' IN SCHEMA {DATABASE}.{ML_SCHEMA}"
        ).collect()
        for row in rows:
            d = row.as_dict()
            print(f"  {d.get('name')}: {d.get('status') or d.get('state')} "
                  f"(pool {d.get('compute_pool')})")
        print("\nNext: deploy the inference UI with "
              "`python3 scripts/deploy_streamlit.py --app inference`.")
    finally:
        session.close()


if __name__ == "__main__":
    main()

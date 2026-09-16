"""Upload the Phase 3/4/6 Notebooks to the CAR_MULTIMODAL_AI Workspace.

Legacy `CREATE NOTEBOOK ... FROM stage` objects are deprecated (Snowflake disables
creating new Legacy Notebooks starting Sept 1, 2026) in favor of Notebooks in
Workspaces. This script PUTs each notebook (plus its `src/`/`conf/` dependencies)
into the `ML.CAR_MULTIMODAL_AI` workspace's live version and commits it — there is
no separate NOTEBOOK object to create; open the .ipynb file directly from Snowsight
(Projects > Workspaces > CAR_MULTIMODAL_AI) and run its cells yourself (each notebook
contains its own acceptance-criteria checks).

The workspace mirrors the repo layout (`notebooks/`, `src/`, `conf/` as siblings) so
`phase6_model_dev.ipynb`'s `sys.path.insert(0, "..")` + `from src...` imports resolve
the same way they do locally. Phase 3/4 don't need `src/`/`conf/`, but uploading them
for all three keeps this script simple and the workspace self-consistent.

Notebooks in Workspaces only run on Container Runtime (`MULTIMODAL_CPU_POOL` by
default, selectable per-notebook in Snowsight), matching the ML Jobs used for the
other phases.

Usage (run from the project root):

    export SNOWFLAKE_CONNECTION_NAME=<your-connection>
    python3 scripts/upload_notebooks.py            # upload all 3 (Phase 3, 4, 6)
    python3 scripts/upload_notebooks.py --phase 6  # upload just one
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowpark_session import create_snowpark_session  # noqa: E402

DATABASE = "CAR_MULTIMODAL_AI_DB"
SCHEMA = "ML"
WORKSPACE = f"{DATABASE}.{SCHEMA}.CAR_MULTIMODAL_AI"
WORKSPACE_LIVE = f"snow://workspace/{WORKSPACE}/versions/live"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Uploaded once, shared by all 3 notebooks (only Phase 6 actually imports these,
# but keeping the layout consistent keeps this script simple).
DEPENDENCY_DIRS = ["src", "conf"]

NOTEBOOKS = {
    3: {
        "file": "phase3_load_tables.ipynb",
        "comment": "Phase 3: finalize SENSORS/SPLITS table registration",
    },
    4: {
        "file": "phase4_eda.ipynb",
        "comment": "Phase 4: data visualization / EDA",
    },
    6: {
        "file": "phase6_model_dev.ipynb",
        "comment": "Phase 6: sensor/image/fusion model dev, small-scale validation",
    },
}


def ensure_live_version(session) -> None:
    """A mutable live version must exist before PUT; add one if none is active yet."""
    try:
        session.sql(f"ALTER WORKSPACE {WORKSPACE} ADD LIVE VERSION FROM LAST").collect()
    except Exception as exc:  # noqa: BLE001 - only tolerate "already has a live version"
        if "live version" not in str(exc).lower():
            raise


def upload_dependencies(session) -> None:
    print("=== Uploading src/ + conf/ (shared by the notebooks) ===")
    for dirname in DEPENDENCY_DIRS:
        local_dir = PROJECT_ROOT / dirname
        for local_file in sorted(local_dir.glob("*")):
            if not local_file.is_file():
                continue
            target = f"{WORKSPACE_LIVE}/{dirname}"
            results = session.file.put(
                str(local_file), target, auto_compress=False, overwrite=True
            )
            for r in results:
                print(f"  PUT {r.source} -> {r.target}: {r.status}")


def upload_notebook(session, phase: int) -> None:
    info = NOTEBOOKS[phase]
    local_path = PROJECT_ROOT / "notebooks" / info["file"]
    print(f"\n=== Phase {phase}: {info['file']} ===")

    target = f"{WORKSPACE_LIVE}/notebooks"
    put_results = session.file.put(
        str(local_path), target, auto_compress=False, overwrite=True
    )
    for r in put_results:
        print(f"  PUT {r.source} -> {r.target}: {r.status}")
    print(f"  Uploaded to workspace: {WORKSPACE}:/notebooks/{info['file']}")


@click.command()
@click.option(
    "--phase",
    type=click.Choice([str(p) for p in sorted(NOTEBOOKS)]),
    default=None,
    help="Upload a single phase's notebook (default: all of 3, 4, 6)",
)
def main(phase: str | None) -> None:
    session = create_snowpark_session()
    try:
        session.use_database(DATABASE)
        session.use_schema(SCHEMA)
        ensure_live_version(session)
        upload_dependencies(session)
        phases = [int(phase)] if phase else sorted(NOTEBOOKS)
        for p in phases:
            upload_notebook(session, p)
        # Shared workspace: uploads stay in the live version until committed. COMMIT
        # publishes them (visible via /versions/head/) and destroys the live version
        # (ensure_live_version() recreates it on the next run).
        session.sql(f"ALTER WORKSPACE {WORKSPACE} COMMIT").collect()
        print(
            f"\nCommitted. Open the workspace in Snowsight: "
            f"Projects > Workspaces > {WORKSPACE.split('.')[-1]} > notebooks/\n"
            "Remember: if a Notebook's kernel is already running, restart it after a "
            "re-upload — an already-running kernel keeps its old in-memory copy of any "
            "`src/*.py` module it previously imported."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()

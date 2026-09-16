"""Shared ML Job submission helper for car_multimodal_ai_sample.

Run all `scripts/submit_phase*.py` from the **project root**
(`car_multimodal_ai_sample/`), not from inside `scripts/`, so that
`stage_payload()` below resolves the project correctly.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowpark_session import create_snowpark_session  # noqa: E402

DATABASE = "CAR_MULTIMODAL_AI_DB"
COMPUTE_POOL = "MULTIMODAL_CPU_POOL"
JOB_STAGE = f"@{DATABASE}.CURATED.JOB_STAGE"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Everything a jobs/*.py entrypoint actually needs at runtime: the job scripts
# themselves, the shared library they import, and the YAML they read. Notebooks,
# READMEs, tests, streamlit/, and scripts/ are never imported inside a job.
PAYLOAD_DIRS = ("jobs", "src", "conf")


def _stage_payload_dir(stack) -> Path:
    """Copy just PAYLOAD_DIRS into a temp dir and return it, for submit_directory().

    Why not hand `submit_directory()` the project root directly (which is what the
    obvious implementation does)? Two real failures, both reproduced against this
    account:

    1. `snowflake.ml.jobs._utils.payload_utils._upload_directory()` batches files
       into glob patterns, and for a *hidden, suffix-less* file it emits the
       pattern `<dir>/.*`. The project root always has one — `.gitignore` — so the
       pattern `<project_root>/.*` gets PUT, and that glob also matches every
       dot-*directory* in the root. `PUT` then dies with
       `253006: Not a file but a directory: .../<some-dot-dir>`. Any dot-directory
       is enough to break submission: `.pytest_cache/` and `.ruff_cache/` from a
       test run, `.cortex/` from Cortex Code, `.git/`, `.idea/`, `.venv/`.
    2. There is no ignore/exclude hook — `submit_directory()` uploads whatever is
       under the path it's given, and it does not read `.gitignore`. A `.venv`
       created inside the project root (which is exactly what the README's own
       `uv venv .venv` line used to produce) is therefore staged in full, adding
       ~1.2 GB of torch wheels to every single job submission.

    Copying an explicit allowlist sidesteps both: the payload is a few hundred KB,
    deterministic, and contains no dot-entries at all.
    """
    tmp_root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="car_mm_payload_")))
    for name in PAYLOAD_DIRS:
        src = PROJECT_ROOT / name
        if not src.is_dir():
            raise FileNotFoundError(
                f"expected {src} to exist — run submit_phase*.py from the project root"
            )
        shutil.copytree(
            src,
            tmp_root / name,
            # __pycache__ would be skipped by the uploader anyway; dotfiles are the
            # ones that actually break it (see above).
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".*"),
        )
    return tmp_root


def get_session(schema: str = "RAW"):
    session = create_snowpark_session()
    session.use_database(DATABASE)
    session.use_schema(schema)
    return session


def submit(
    entrypoint: str,
    job_args: list[str],
    pip_requirements: list[str] | None = None,
    external_access_integrations: list[str] | None = None,
    schema: str = "RAW",
    target_instances: int = 1,
):
    import contextlib

    from snowflake.ml.jobs import submit_directory

    session = get_session(schema)
    with contextlib.ExitStack() as stack:
        payload_dir = _stage_payload_dir(stack)
        job = submit_directory(
            str(payload_dir),
            COMPUTE_POOL,
            entrypoint=entrypoint,
            stage_name=JOB_STAGE,
            args=job_args,
            # target_instances > 1 provisions that many compute-pool nodes and forms
            # a Ray cluster across them automatically (Container Runtime handles Ray
            # bootstrapping); job code just needs to submit Ray tasks/datasets and
            # Ray's scheduler spreads them across every node in the cluster.
            target_instances=target_instances,
            pip_requirements=pip_requirements or [],
            external_access_integrations=external_access_integrations or [],
            session=session,
            # Local dev python is 3.13; the SDK defaults to matching the *local*
            # interpreter version, but no 3.13 Container Runtime image exists yet.
            # Passing "" (not None) skips that auto-detection and falls back to the
            # compute pool's default runtime image (verified via
            # `CALL SYSTEM$GET_ML_JOB_RUNTIME('MULTIMODAL_CPU_POOL', '')`).
            runtime_environment="",
        )
    print(f"Job submitted: id={job.id} (target_instances={target_instances})")
    print(f"Status: {job.status}")
    return job



def wait_and_report(job) -> None:
    job.wait()
    print(f"Final status: {job.status}")
    print(job.get_logs())

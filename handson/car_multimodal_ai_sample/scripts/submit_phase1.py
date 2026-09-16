"""Submit jobs/phase1_ingest_raw.py as a Snowflake ML Job.

Run from the project root:

    python3 scripts/submit_phase1.py --dry-run --limit 3   # smoke test
    python3 scripts/submit_phase1.py                        # full Chunk_1 run, 8 threads by default
    python3 scripts/submit_phase1.py --concurrency 1         # sequential staging (no threading)
    python3 scripts/submit_phase1.py --wait                  # block until job finishes
"""

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _submit_common import submit, wait_and_report  # noqa: E402


@click.command()
@click.option("--dry-run", is_flag=True)
@click.option("--limit", type=int, default=None)
@click.option("--wait", is_flag=True)
@click.option(
    "--concurrency",
    type=int,
    default=None,
    help="threads used to stage segments concurrently within a chunk (each thread "
    "opens its own Snowpark session); defaults to jobs/phase1_ingest_raw.py's own "
    "default (8) if omitted; pass 1 for strictly sequential staging",
)
def main(dry_run: bool, limit: int | None, wait: bool, concurrency: int | None) -> None:
    job_args = []
    if dry_run:
        job_args.append("--dry-run")
    if limit:
        job_args += ["--limit", str(limit)]
    if concurrency is not None:
        job_args += ["--concurrency", str(concurrency)]

    job = submit(
        entrypoint="jobs/phase1_ingest_raw.py",
        job_args=job_args,
        pip_requirements=["huggingface_hub", "click"],
        external_access_integrations=["HF_ACCESS_INTEGRATION", "PYPI_ACCESS_INTEGRATION"],
        schema="RAW",
    )

    if wait:
        wait_and_report(job)


if __name__ == "__main__":
    main()

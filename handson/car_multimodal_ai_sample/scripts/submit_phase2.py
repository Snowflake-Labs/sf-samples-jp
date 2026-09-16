"""Submit jobs/phase2_extract_organize.py as a Snowflake ML Job.

    python3 scripts/submit_phase2.py --dry-run --limit 3
    python3 scripts/submit_phase2.py                 # default: 4-node Ray cluster, auto-distributed
    python3 scripts/submit_phase2.py --nodes 1       # single-node (no multi-node distribution)
    python3 scripts/submit_phase2.py --wait
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
    "--nodes",
    type=click.IntRange(min=1),
    default=4,
    show_default=True,
    help="number of MULTIMODAL_CPU_POOL nodes to request (target_instances); "
    "job code parallelizes segment processing across all of them via Ray "
    "(the default, 4, always runs a multi-node Ray cluster; pass --nodes 1 "
    "for a single-node run)",
)
def main(dry_run: bool, limit: int | None, wait: bool, nodes: int) -> None:
    job_args = []
    if dry_run:
        job_args.append("--dry-run")
    if limit:
        job_args += ["--limit", str(limit)]

    job = submit(
        entrypoint="jobs/phase2_extract_organize.py",
        job_args=job_args,
        pip_requirements=["av", "click"],
        external_access_integrations=["PYPI_ACCESS_INTEGRATION"],
        schema="CURATED",
        target_instances=nodes,
    )

    if wait:
        wait_and_report(job)


if __name__ == "__main__":
    main()

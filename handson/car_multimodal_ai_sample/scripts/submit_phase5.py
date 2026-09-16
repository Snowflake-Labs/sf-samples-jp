"""Submit jobs/phase5_extract_embeddings.py as a Snowflake ML Job.

    python3 scripts/submit_phase5.py --dry-run --limit 50
    python3 scripts/submit_phase5.py                 # default: 4-node Ray cluster, auto-distributed
    python3 scripts/submit_phase5.py --nodes 1       # single-node (no multi-node distribution)
    python3 scripts/submit_phase5.py --wait
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
    "ray.data.read_datasource/map_batches automatically distributes work across "
    "all of them with no job-script changes (the default, 4, always runs a "
    "multi-node Ray cluster; pass --nodes 1 for a single-node run)",
)
def main(dry_run: bool, limit: int | None, wait: bool, nodes: int) -> None:
    job_args = []
    if dry_run:
        job_args.append("--dry-run")
    if limit:
        job_args += ["--limit", str(limit)]

    job = submit(
        entrypoint="jobs/phase5_extract_embeddings.py",
        job_args=job_args,
        pip_requirements=["click"],
        external_access_integrations=["PYTORCH_HUB_ACCESS_INTEGRATION"],
        schema="CURATED",
        target_instances=nodes,
    )

    if wait:
        wait_and_report(job)


if __name__ == "__main__":
    main()

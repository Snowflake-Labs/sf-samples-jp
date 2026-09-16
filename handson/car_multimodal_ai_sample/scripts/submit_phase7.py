"""Submit jobs/phase7_train_distributed.py as a Snowflake ML Job.

    python3 scripts/submit_phase7.py --dry-run --max-samples 500
    python3 scripts/submit_phase7.py                           # default: real DDP across 4 nodes
    python3 scripts/submit_phase7.py --modality fusion --wait
    python3 scripts/submit_phase7.py --nodes 1                 # single-node smoke test (no DDP)
    python3 scripts/submit_phase7.py --nodes 8                 # scale out further
"""

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _submit_common import submit, wait_and_report  # noqa: E402


@click.command()
@click.option("--dry-run", is_flag=True)
@click.option("--modality", type=click.Choice(["sensor", "image", "fusion"]), default=None)
@click.option("--max-samples", type=int, default=None)
@click.option("--wait", is_flag=True)
@click.option(
    "--nodes",
    type=click.IntRange(min=1),
    default=4,
    show_default=True,
    help="number of MULTIMODAL_CPU_POOL nodes to request (target_instances) AND "
    "conf/train.yaml: distributed.num_nodes override; >1 trains each modality "
    "with real torch.distributed DDP across that many nodes (the default, 4, "
    "always runs real DDP; pass --nodes 1 for a single-node smoke test)",
)
def main(
    dry_run: bool, modality: str | None, max_samples: int | None, wait: bool, nodes: int
) -> None:
    job_args = []
    if dry_run:
        job_args.append("--dry-run")
    if modality:
        job_args += ["--modality", modality]
    if max_samples:
        job_args += ["--max-samples", str(max_samples)]
    # Always forward --nodes explicitly (not just when != 1): the job's own
    # default comes from conf/train.yaml, so if this script's default ever
    # differs from that file's, or a caller explicitly asks for --nodes 1,
    # omitting the flag here would silently fall back to the wrong value.
    job_args += ["--nodes", str(nodes)]

    job = submit(
        entrypoint="jobs/phase7_train_distributed.py",
        job_args=job_args,
        pip_requirements=["click"],
        external_access_integrations=[],
        schema="ML",
        target_instances=nodes,
    )

    if wait:
        wait_and_report(job)


if __name__ == "__main__":
    main()

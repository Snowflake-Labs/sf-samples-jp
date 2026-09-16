"""Teardown — remove every resource created by `scripts/setup.py`.
Runs `infra/03_teardown.sql`.

Drops:
    SERVICE ML.LEAD_DISTANCE_{SENSOR,IMAGE,FUSION}_SVC (Phase 9 inference services;
        dropped first — a compute pool with active services can't be dropped)
    DATABASE CAR_MULTIMODAL_AI_DB (cascades: all schemas/tables/stages/
        notebooks/streamlit objects/experiments/registry models)
    WAREHOUSE MULTIMODAL_WH
    COMPUTE POOL MULTIMODAL_CPU_POOL / MULTIMODAL_GPU_POOL / MULTIMODAL_SERVING_POOL
    EXTERNAL ACCESS INTEGRATION HF_ACCESS_INTEGRATION
    ROLE MULTIMODAL_APP_ROLE

This is irreversible. By default the script prints the target account/user and
asks for interactive confirmation before running; pass --yes to skip the prompt
(e.g. for CI).

Usage (run from the project root):

    export SNOWFLAKE_CONNECTION_NAME=<your-connection>
    python3 scripts/teardown.py            # asks for confirmation
    python3 scripts/teardown.py --yes      # no prompt
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sql_common import run_sql_file  # noqa: E402
from snowpark_session import create_snowpark_session  # noqa: E402

SQL_PATH = Path(__file__).resolve().parent.parent / "infra" / "03_teardown.sql"


@click.command()
@click.option("--yes", is_flag=True, help="skip the confirmation prompt")
def main(yes: bool) -> None:
    session = create_snowpark_session()
    try:
        account = session.get_current_account()
        user = session.get_current_user()
        print(f"Target account: {account}   user: {user}")
        print("This will PERMANENTLY drop CAR_MULTIMODAL_AI_DB, MULTIMODAL_WH, "
              "MULTIMODAL_CPU_POOL/GPU_POOL/SERVING_POOL, the Phase 9 inference "
              "services, HF_ACCESS_INTEGRATION, MULTIMODAL_APP_ROLE.")

        if not yes:
            reply = input("Type 'yes' to continue: ").strip().lower()
            if reply != "yes":
                print("Aborted.")
                return

        print(f"\n=== Running {SQL_PATH.relative_to(SQL_PATH.parent.parent)} ===")
        run_sql_file(session, SQL_PATH)
        print("\nTeardown complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()

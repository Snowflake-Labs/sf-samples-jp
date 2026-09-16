"""Setup — build the initial Snowflake environment for car_multimodal_ai_sample.
Runs `infra/01_setup_database.sql` and `infra/02_external_access.sql`.

Creates (all `IF NOT EXISTS`, safe to re-run):
    DATABASE     CAR_MULTIMODAL_AI_DB (schemas RAW / CURATED / ML / APP)
    WAREHOUSE    MULTIMODAL_WH
    COMPUTE POOL MULTIMODAL_CPU_POOL (required) / MULTIMODAL_GPU_POOL (optional)
    ROLE         MULTIMODAL_APP_ROLE
    Stages       RAW.RAW_STAGE, CURATED.IMAGES_STAGE, CURATED.FEATURES_STAGE,
                 CURATED.MISC_STAGE, CURATED.JOB_STAGE
    WORKSPACE    ML.CAR_MULTIMODAL_AI (holds the Phase 3/4/6 Notebooks in Workspaces)
    NETWORK RULE + EXTERNAL ACCESS INTEGRATION for Hugging Face / PyPI / PyTorch Hub

Requires an ACCOUNTADMIN-equivalent connection (infra/01 and infra/02 both start
with `USE ROLE ACCOUNTADMIN`).

Usage (run from the project root):

    export SNOWFLAKE_CONNECTION_NAME=<your-connection>
    python3 scripts/setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sql_common import run_sql_file  # noqa: E402
from snowpark_session import create_snowpark_session  # noqa: E402

INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"
SQL_FILES = ["01_setup_database.sql", "02_external_access.sql"]


def main() -> None:
    session = create_snowpark_session()
    try:
        print(f"Connected as {session.get_current_user()} "
              f"(account {session.get_current_account()}, role {session.get_current_role()})")
        for name in SQL_FILES:
            path = INFRA_DIR / name
            print(f"\n=== Running {path.relative_to(INFRA_DIR.parent)} ===")
            run_sql_file(session, path)
        print("\nSetup complete. Next: submit Phase 1 with "
              "`python3 scripts/submit_phase1.py --dry-run --limit 3`.")
    finally:
        session.close()


if __name__ == "__main__":
    main()

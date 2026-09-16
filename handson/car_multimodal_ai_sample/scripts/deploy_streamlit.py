"""Deploy this project's Streamlit-in-Snowflake apps.

Two apps live in `streamlit/`, both reading live from Snowflake:

* `app.py` -> `APP.LEAD_DISTANCE_DASHBOARD` (Phase 8): the ablation comparison
  dashboard, reading `ML.LEAD_DISTANCE_ESTIMATION` (Experiments) and the
  `ML.LEAD_DISTANCE_*` Model Registry entries. Redeploy after Phase 7 produces
  new runs to compare.
* `inference_app.py` -> `APP.LEAD_DISTANCE_INFERENCE` (Phase 9): the online
  inference UI, sending single samples to the SPCS inference services created by
  `scripts/deploy_serving.py`. Requires those services to be running.

Both apps share one stage (`APP.STREAMLIT_STAGE`) and are distinguished by
MAIN_FILE, so a single upload serves both.

Usage (run from the project root):

    export SNOWFLAKE_CONNECTION_NAME=<your-connection>
    python3 scripts/deploy_streamlit.py                      # both apps
    python3 scripts/deploy_streamlit.py --app comparison      # Phase 8 only
    python3 scripts/deploy_streamlit.py --app inference       # Phase 9 only
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snowpark_session import create_snowpark_session  # noqa: E402

DATABASE = "CAR_MULTIMODAL_AI_DB"
SCHEMA = "APP"
STAGE = f"@{DATABASE}.{SCHEMA}.STREAMLIT_STAGE"
WAREHOUSE = "MULTIMODAL_WH"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STREAMLIT_DIR = PROJECT_ROOT / "streamlit"

APPS = {
    "comparison": {
        "main_file": "app.py",
        "object": "LEAD_DISTANCE_DASHBOARD",
        "comment": "Phase 8: sensor/image/fusion ablation comparison (Experiments + Registry)",
    },
    "inference": {
        "main_file": "inference_app.py",
        "object": "LEAD_DISTANCE_INFERENCE",
        "comment": "Phase 9: online inference UI against the SPCS Model Serving endpoints",
    },
}


def deploy_app(session, key: str) -> str:
    spec = APPS[key]
    object_name = f"{DATABASE}.{SCHEMA}.{spec['object']}"
    print(f"\n=== Creating STREAMLIT object for '{key}' ({spec['main_file']}) ===")
    session.sql(
        f"""CREATE STREAMLIT IF NOT EXISTS {object_name}
            ROOT_LOCATION = '{STAGE}'
            MAIN_FILE = '{spec["main_file"]}'
            QUERY_WAREHOUSE = '{WAREHOUSE}'
            COMMENT = '{spec["comment"]}'"""
    ).collect()
    rows = session.sql(
        f"SHOW STREAMLITS LIKE '{spec['object']}' IN SCHEMA {SCHEMA}"
    ).collect()
    for row in rows:
        print(f"  {row}")
    return object_name


@click.command()
@click.option(
    "--app",
    "app_key",
    type=click.Choice(["comparison", "inference", "all"]),
    default="all",
    show_default=True,
    help="which Streamlit app(s) to deploy",
)
def main(app_key: str) -> None:
    """Upload streamlit/ to the APP stage and (re)create the STREAMLIT object(s)."""
    keys = list(APPS) if app_key == "all" else [app_key]
    session = create_snowpark_session()
    try:
        session.use_database(DATABASE)
        session.use_schema(SCHEMA)

        print("=== Creating stage (if needed) ===")
        session.sql(
            f"""CREATE STAGE IF NOT EXISTS {SCHEMA}.STREAMLIT_STAGE
                ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
                DIRECTORY  = (ENABLE = TRUE)
                COMMENT    = 'streamlit/*.py + environment.yml for the Phase 8/9 apps'"""
        ).collect()

        # Upload every app file plus the shared environment.yml, regardless of which
        # object is being (re)created — the stage is shared and this keeps both apps'
        # code in sync with the repo.
        print("=== Uploading app files + environment.yml ===")
        filenames = ["environment.yml"] + [APPS[k]["main_file"] for k in APPS]
        for filename in filenames:
            results = session.file.put(
                str(STREAMLIT_DIR / filename), STAGE, auto_compress=False, overwrite=True
            )
            for r in results:
                print(f"  PUT {r.source} -> {r.target}: {r.status}")

        # inference_app.py imports the shared prediction-path helpers. A
        # Streamlit-in-Snowflake app can only import modules that sit next to it on
        # its stage, so src/serving.py is uploaded flat as `serving.py` (the app
        # tries `import serving` first, then falls back to `src.serving` locally).
        print("=== Uploading shared module (src/serving.py -> serving.py) ===")
        for r in session.file.put(
            str(PROJECT_ROOT / "src" / "serving.py"), STAGE, auto_compress=False, overwrite=True
        ):
            print(f"  PUT {r.source} -> {r.target}: {r.status}")

        deployed = [deploy_app(session, key) for key in keys]

        print("\nDeployed:")
        for name in deployed:
            print(f"  {name}")
        print("Open them in Snowsight: Projects > Streamlit")
        print(
            "Note: the app files are re-read live from the stage on each viewer session — "
            "re-running this script after an edit is enough, no need to recreate the object."
        )
        if "inference" in keys:
            print(
                "\nLEAD_DISTANCE_INFERENCE needs the Phase 9 services running: "
                "`python3 scripts/deploy_serving.py`"
            )
    finally:
        session.close()


if __name__ == "__main__":
    main()

"""Snowflake の ML 結果を Postgres の hr_lake（pg_lake の Iceberg テーブル）にコピーする（任意の手順）。

pg_lake は Postgres の STANDARD 以上の階層が必要。ML パイプラインや再推論の後に実行する。
"""
import os
import sys
import psycopg2
import psycopg2.extras
import snowflake.connector
import time

PG_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "dbname": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.environ["POSTGRES_USER"],
    "password": os.getenv("POSTGRES_PASSWORD"),
}

TABLES = [
    {
        "name": "prediction_results",
        "sf_sql": "SELECT ID, EMPLOYEE_ID, RUN_DATE, RISK_SCORE, RISK_LABEL, MODEL_VERSION FROM HR_ANALYTICS.PUBLIC.PREDICTION_RESULTS",
        "pg_create": """CREATE TABLE hr_lake.prediction_results (
            id BIGINT, employee_id BIGINT, run_date DATE,
            risk_score DOUBLE PRECISION, risk_label TEXT, model_version TEXT
        ) USING pg_lake_iceberg""",
        "pg_insert": "INSERT INTO hr_lake.prediction_results (id, employee_id, run_date, risk_score, risk_label, model_version) VALUES %s",
    },
    {
        "name": "relationship_results",
        "sf_sql": "SELECT ID, MANAGER_ID, EMPLOYEE_ID, RELATIONSHIP_SCORE, COMPOSITE_LABEL, MODEL_VERSION FROM HR_ANALYTICS.PUBLIC.RELATIONSHIP_RESULTS",
        "pg_create": """CREATE TABLE hr_lake.relationship_results (
            id BIGINT, manager_id BIGINT, employee_id BIGINT,
            relationship_score DOUBLE PRECISION, composite_label BIGINT, model_version TEXT
        ) USING pg_lake_iceberg""",
        "pg_insert": "INSERT INTO hr_lake.relationship_results (id, manager_id, employee_id, relationship_score, composite_label, model_version) VALUES %s",
    },
    {
        "name": "shap_results",
        "sf_sql": "SELECT PREDICTION_ID, MODEL_TYPE, FEATURE_NAME, SHAP_VALUE, FEATURE_VALUE FROM HR_ANALYTICS.PUBLIC.SHAP_RESULTS",
        "pg_create": """CREATE TABLE hr_lake.shap_results (
            prediction_id BIGINT, model_type TEXT, feature_name TEXT,
            shap_value DOUBLE PRECISION, feature_value DOUBLE PRECISION
        ) USING pg_lake_iceberg""",
        "pg_insert": "INSERT INTO hr_lake.shap_results (prediction_id, model_type, feature_name, shap_value, feature_value) VALUES %s",
    },
    {
        "name": "evidence_store",
        "sf_sql": "SELECT EMPLOYEE_ID, SCORE_TYPE, PREDICTION_ID, EVIDENCE_JSON::STRING, GENERATED_AT FROM HR_ANALYTICS.PUBLIC.EVIDENCE_STORE",
        "pg_create": """CREATE TABLE hr_lake.evidence_store (
            employee_id BIGINT, score_type TEXT, prediction_id BIGINT,
            evidence_json TEXT, generated_at TIMESTAMP
        ) USING pg_lake_iceberg""",
        "pg_insert": "INSERT INTO hr_lake.evidence_store (employee_id, score_type, prediction_id, evidence_json, generated_at) VALUES %s",
    },
    {
        "name": "similar_cases",
        "sf_sql": "SELECT SCORE_TYPE, SOURCE_EMPLOYEE_ID, SIMILAR_EMPLOYEE_ID, SIMILARITY_SCORE, OUTCOME, COMMON_FACTORS::STRING, COMPUTED_AT FROM HR_ANALYTICS.PUBLIC.SIMILAR_CASES",
        "pg_create": """CREATE TABLE hr_lake.similar_cases (
            score_type TEXT, source_employee_id BIGINT, similar_employee_id BIGINT,
            similarity_score DOUBLE PRECISION, outcome TEXT, common_factors TEXT, computed_at TIMESTAMP
        ) USING pg_lake_iceberg""",
        "pg_insert": "INSERT INTO hr_lake.similar_cases (score_type, source_employee_id, similar_employee_id, similarity_score, outcome, common_factors, computed_at) VALUES %s",
    },
]

BATCH_SIZE = 5000


def main():
    print("=== Sync ML Results -> pg_lake Iceberg Tables ===", flush=True)

    sf_conn = snowflake.connector.connect(
        connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME") or "default"
    )
    pg_conn = psycopg2.connect(**PG_CONFIG)
    pg_conn.autocommit = True

    sf_cur = sf_conn.cursor()
    pg_cur = pg_conn.cursor()

    pg_cur.execute("CREATE EXTENSION IF NOT EXISTS pg_lake CASCADE")
    pg_cur.execute("CREATE SCHEMA IF NOT EXISTS hr_lake")

    total_start = time.time()

    for tbl in TABLES:
        t0 = time.time()
        name = tbl["name"]

        print(f"\n  [{name}]", flush=True)
        print(f"    Fetching from Snowflake...", end="", flush=True)
        sf_cur.execute(tbl["sf_sql"])
        rows = sf_cur.fetchall()
        fetch_t = time.time() - t0
        print(f" {len(rows):,} rows ({fetch_t:.1f}s)", flush=True)

        if not rows:
            print("    skip (empty)")
            continue

        print(f"    DROP + CREATE (clean Parquet)...", end="", flush=True)
        pg_cur.execute(f"DROP TABLE IF EXISTS hr_lake.{name}")
        pg_cur.execute(tbl["pg_create"])
        print(" done", flush=True)

        print(f"    Inserting...", end="", flush=True)
        ins_start = time.time()
        loaded = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            psycopg2.extras.execute_values(pg_cur, tbl["pg_insert"], batch, page_size=BATCH_SIZE)
            loaded += len(batch)
            pct = loaded * 100 // len(rows)
            elapsed = time.time() - ins_start
            rate = loaded / elapsed if elapsed > 0 else 0
            print(f"\r    Inserting... {loaded:,}/{len(rows):,} ({pct}%) [{rate:.0f} rows/s]", end="", flush=True)

        elapsed = time.time() - t0
        print(f"\n    Done ({elapsed:.1f}s total)", flush=True)

    total = time.time() - total_start
    print(f"\n=== Sync complete ({total:.0f}s) ===", flush=True)

    print("Triggering object store catalog generation...", end="", flush=True)
    pg_cur.execute("SELECT lake_iceberg.trigger_object_store_catalog_generation()")
    print(" done", flush=True)

    sf_cur.close()
    sf_conn.close()
    pg_cur.close()
    pg_conn.close()


if __name__ == "__main__":
    main()

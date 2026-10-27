-- 07_parallel_fanout/sql/20_objects.sql
-- Parallel fan-out/fan-in: result tables, worker and aggregation procedures, and inspection views.
-- Sibling worker tasks run concurrently and write results to REVIEW_FINDINGS by RUN_ID.
-- Procedure return values are not task return values, so fan-in reads the result table.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.REVIEW_RUNS (
    RUN_ID      STRING NOT NULL PRIMARY KEY,
    PROJECT_ID  STRING NOT NULL,
    MODE        STRING NOT NULL,            -- PARALLEL | SEQUENTIAL
    STATUS      STRING NOT NULL,            -- RUNNING | DONE | PARTIAL
    STARTED_AT  TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    FINISHED_AT TIMESTAMP_LTZ
) COMMENT = 'Pattern 07: one row per project review run';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.REVIEW_FINDINGS (
    RUN_ID      STRING NOT NULL,
    PERSPECTIVE STRING NOT NULL,            -- schedule | ownership | quality
    AGENT_NAME  STRING,
    STATUS      STRING NOT NULL,            -- OK | ERROR
    FINDINGS    VARIANT,
    ERROR       STRING,
    STARTED_AT  TIMESTAMP_LTZ,
    FINISHED_AT TIMESTAMP_LTZ,
    ELAPSED_MS  NUMBER
) COMMENT = 'Pattern 07: one row per reviewer (fan-out worker) result';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.REVIEW_REPORTS (
    RUN_ID     STRING NOT NULL PRIMARY KEY,
    PROJECT_ID STRING NOT NULL,
    REPORT     VARIANT,
    CREATED_AT TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Pattern 07: aggregated (fan-in) review report';

-------------------------------------------------------------------------------
-- Worker: review.PERSPECTIVES fixes each perspective to one agent. Record agent failures as ERROR instead of raising.
-- If this procedure itself fails, the finalizer still runs fan-in and creates a partial report.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.RUN_REVIEW_WORKER(PERSPECTIVE STRING, RUN_ID STRING, PROJECT_ID STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Pattern 07 fan-out worker: run one reviewer agent for one project and store its findings'
EXECUTE AS OWNER
AS
$$
import json
import time

from src import review
from src.agent_client import run_agent

DB = "<% db %>"


def run(session, perspective, run_id, project_id):
    # Use epoch milliseconds because returning a datetime loses timezone information.
    started_ms = session.sql("SELECT DATE_PART(epoch_millisecond, CURRENT_TIMESTAMP()) AS T").collect()[0]["T"]
    t0 = time.time()
    agent, status, findings, error = None, "ERROR", [], None
    try:
        agent = review.agent_for(perspective)
        rows = session.sql(f"SELECT OBJECT_CONSTRUCT_KEEP_NULL('task_id', TASK_ID, 'title', TITLE, 'status', STATUS, "
                           f"'priority', PRIORITY, 'assignee', ASSIGNEE, 'due_date', TO_VARCHAR(DUE_DATE), "
                           f"'acceptance_criteria', ACCEPTANCE_CRITERIA) AS T FROM {DB}.APP.TASKS "
                           f"WHERE PROJECT_ID = ? ORDER BY TASK_ID", params=[project_id]).collect()
        tasks = [json.loads(r["T"]) for r in rows]
        today = session.sql("SELECT TO_VARCHAR(CURRENT_DATE()) AS D").collect()[0]["D"]
        result = run_agent(session, f"{DB}.AGENTS.{agent}", review.build_prompt(perspective, project_id, today, tasks))
        if not result.ok:
            raise ValueError(result.error)
        findings = review.parse_findings(result.text, perspective, {t["task_id"] for t in tasks})
        status = "OK"
    except Exception as exc:  # recorded, never raised: the fan-in must still run
        error = str(exc)[:500]
    session.sql(f"INSERT INTO {DB}.INTERNAL.REVIEW_FINDINGS (RUN_ID, PERSPECTIVE, AGENT_NAME, STATUS, FINDINGS, "
                f"ERROR, STARTED_AT, FINISHED_AT, ELAPSED_MS) SELECT ?, ?, ?, ?, PARSE_JSON(?), ?, "
                f"TO_TIMESTAMP_LTZ(?, 3), "
                f"CURRENT_TIMESTAMP(), ?",
                params=[run_id, perspective, agent, status, json.dumps(findings, ensure_ascii=False), error,
                        int(started_ms), int((time.time() - t0) * 1000)]).collect()
    return status
$$;

-------------------------------------------------------------------------------
-- Deterministic fan-in: merge findings per task, keep the highest severity, and mark missing perspectives as partial.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.AGGREGATE_REVIEW(RUN_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Pattern 07 fan-in: merge reviewer findings into one report (deterministic, no LLM)'
EXECUTE AS OWNER
AS
$$
import json

from src import review

DB = "<% db %>"


def run(session, run_id):
    meta = session.sql(f"SELECT PROJECT_ID, MODE FROM {DB}.INTERNAL.REVIEW_RUNS WHERE RUN_ID = ?",
                       params=[run_id]).collect()
    if not meta:
        return {"ok": False, "error": f"run {run_id} not found"}
    rows = session.sql(f"SELECT PERSPECTIVE, STATUS, FINDINGS FROM {DB}.INTERNAL.REVIEW_FINDINGS WHERE RUN_ID = ?",
                       params=[run_id]).collect()
    workers = [{"perspective": r["PERSPECTIVE"], "status": r["STATUS"],
                "findings": json.loads(r["FINDINGS"]) if r["FINDINGS"] else []} for r in rows]
    report = review.aggregate(run_id, meta[0]["PROJECT_ID"], meta[0]["MODE"], workers)
    session.sql(f"DELETE FROM {DB}.INTERNAL.REVIEW_REPORTS WHERE RUN_ID = ?", params=[run_id]).collect()
    session.sql(f"INSERT INTO {DB}.INTERNAL.REVIEW_REPORTS (RUN_ID, PROJECT_ID, REPORT) SELECT ?, ?, PARSE_JSON(?)",
                params=[run_id, meta[0]["PROJECT_ID"], json.dumps(report, ensure_ascii=False)]).collect()
    session.sql(f"UPDATE {DB}.INTERNAL.REVIEW_RUNS SET STATUS = ?, FINISHED_AT = CURRENT_TIMESTAMP() WHERE RUN_ID = ?",
                params=["PARTIAL" if report["partial"] else "DONE", run_id]).collect()
    return report
$$;

-------------------------------------------------------------------------------
-- Inspection views.
-------------------------------------------------------------------------------
CREATE OR REPLACE VIEW <% db %>.APP.V_REVIEW_RUNS
COMMENT = 'Pattern 07: review runs with their aggregated report'
AS
SELECT r.RUN_ID, r.PROJECT_ID, r.MODE, r.STATUS, r.STARTED_AT, r.FINISHED_AT,
       DATEDIFF(millisecond, r.STARTED_AT, r.FINISHED_AT) / 1000 AS TOTAL_SECONDS,
       rep.REPORT:tasks_flagged::NUMBER AS TASKS_FLAGGED, rep.REPORT:by_severity AS BY_SEVERITY,
       rep.REPORT:partial::BOOLEAN AS PARTIAL, rep.REPORT AS REPORT
FROM <% db %>.INTERNAL.REVIEW_RUNS r
LEFT JOIN <% db %>.INTERNAL.REVIEW_REPORTS rep ON rep.RUN_ID = r.RUN_ID;

CREATE OR REPLACE VIEW <% db %>.APP.V_REVIEW_WORKERS
COMMENT = 'Pattern 07: one row per reviewer; overlapping start/finish times show parallel execution'
AS
SELECT f.RUN_ID, r.MODE, f.PERSPECTIVE, f.AGENT_NAME, f.STATUS, f.STARTED_AT, f.FINISHED_AT,
       f.ELAPSED_MS / 1000 AS SECONDS, ARRAY_SIZE(f.FINDINGS) AS FINDINGS, f.ERROR
FROM <% db %>.INTERNAL.REVIEW_FINDINGS f
JOIN <% db %>.INTERNAL.REVIEW_RUNS r ON r.RUN_ID = f.RUN_ID;

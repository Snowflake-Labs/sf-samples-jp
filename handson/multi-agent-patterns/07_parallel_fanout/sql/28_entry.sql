-- 07_parallel_fanout/sql/28_entry.sql
-- Owner-rights entry points exposed to the execution role. Do not grant OPERATE on tasks; require these procedures.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- Parallel entry point: start the task graph asynchronously, return RUN_ID, and inspect APP.V_REVIEW_RUNS.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.START_PROJECT_REVIEW(PROJECT_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Pattern 07: start a parallel (task graph) project review; returns the run id'
EXECUTE AS OWNER
AS
$$
import json
import re
import uuid

DB = "<% db %>"


def run(session, project_id):
    pid = (project_id or "").strip().upper()
    if not re.fullmatch(r"PRJ-[A-Z0-9-]{1,30}", pid):
        return {"ok": False, "error": "PROJECT_ID must look like PRJ-PORTAL"}
    if not session.sql(f"SELECT 1 FROM {DB}.APP.PROJECTS WHERE PROJECT_ID = ?", params=[pid]).collect():
        return {"ok": False, "error": f"project {pid} not found"}
    # EXECUTE TASK cannot overlap another run of this graph; reject active runs started within 15 minutes.
    busy = session.sql(f"SELECT RUN_ID FROM {DB}.INTERNAL.REVIEW_RUNS WHERE MODE = 'PARALLEL' AND STATUS = 'RUNNING' "
                       f"AND STARTED_AT > DATEADD(minute, -15, CURRENT_TIMESTAMP())").collect()
    if busy:
        return {"ok": False, "error": f"review {busy[0]['RUN_ID']} is still running; try again later"}
    run_id = "REV-" + uuid.uuid4().hex[:12].upper()
    session.sql(f"INSERT INTO {DB}.INTERNAL.REVIEW_RUNS (RUN_ID, PROJECT_ID, MODE, STATUS) "
                f"SELECT ?, ?, 'PARALLEL', 'RUNNING'", params=[run_id, pid]).collect()
    config = json.dumps({"run_id": run_id, "project_id": pid})   # Values are validated: alphanumeric characters and hyphens only.
    dq = "$" * 2   # Build CONFIG dollar quotes at runtime because dollar quotes delimit this procedure body.
    session.sql(f"EXECUTE TASK {DB}.INTERNAL.REVIEW_ROOT USING CONFIG = {dq}{config}{dq}").collect()
    return {"ok": True, "run_id": run_id, "project_id": pid,
            "message": "started; SELECT * FROM APP.V_REVIEW_RUNS WHERE RUN_ID = '" + run_id + "'"}
$$;

-------------------------------------------------------------------------------
-- Sequential baseline: call the same workers one by one, then run the same fan-in synchronously.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.RUN_PROJECT_REVIEW_SEQUENTIAL(PROJECT_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Pattern 07 baseline: run the same reviewers one after another, then the same fan-in'
EXECUTE AS OWNER
AS
$$
import json
import re
import uuid

DB = "<% db %>"


def run(session, project_id):
    pid = (project_id or "").strip().upper()
    if not re.fullmatch(r"PRJ-[A-Z0-9-]{1,30}", pid):
        return {"ok": False, "error": "PROJECT_ID must look like PRJ-PORTAL"}
    if not session.sql(f"SELECT 1 FROM {DB}.APP.PROJECTS WHERE PROJECT_ID = ?", params=[pid]).collect():
        return {"ok": False, "error": f"project {pid} not found"}
    run_id = "REV-" + uuid.uuid4().hex[:12].upper()
    session.sql(f"INSERT INTO {DB}.INTERNAL.REVIEW_RUNS (RUN_ID, PROJECT_ID, MODE, STATUS) "
                f"SELECT ?, ?, 'SEQUENTIAL', 'RUNNING'", params=[run_id, pid]).collect()
    for perspective in ("schedule", "ownership", "quality"):
        session.call(f"{DB}.INTERNAL.RUN_REVIEW_WORKER", perspective, run_id, pid)
    report = session.call(f"{DB}.INTERNAL.AGGREGATE_REVIEW", run_id)
    return json.loads(report) if isinstance(report, str) else report
$$;

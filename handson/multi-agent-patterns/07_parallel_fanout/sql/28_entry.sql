-- 07_parallel_fanout/sql/28_entry.sql
-- 実行ロールに公開する入口（所有者権限）。タスクの OPERATE は実行ロールに渡さず、ここだけを通す。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- 並列: タスクグラフを起動して RUN_ID を返す（非同期）。結果は APP.V_REVIEW_RUNS で確認する。
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
    # EXECUTE TASK は実行中のグラフに重ねられない。実行中（15 分以内）なら開始しない。
    busy = session.sql(f"SELECT RUN_ID FROM {DB}.INTERNAL.REVIEW_RUNS WHERE MODE = 'PARALLEL' AND STATUS = 'RUNNING' "
                       f"AND STARTED_AT > DATEADD(minute, -15, CURRENT_TIMESTAMP())").collect()
    if busy:
        return {"ok": False, "error": f"review {busy[0]['RUN_ID']} is still running; try again later"}
    run_id = "REV-" + uuid.uuid4().hex[:12].upper()
    session.sql(f"INSERT INTO {DB}.INTERNAL.REVIEW_RUNS (RUN_ID, PROJECT_ID, MODE, STATUS) "
                f"SELECT ?, ?, 'PARALLEL', 'RUNNING'", params=[run_id, pid]).collect()
    config = json.dumps({"run_id": run_id, "project_id": pid})   # 値は検証済み（英数字と - のみ）
    dq = "$" * 2   # プロシージャ本文自体がドル引用符で囲まれているため、CONFIG のドル引用符は実行時に組み立てる
    session.sql(f"EXECUTE TASK {DB}.INTERNAL.REVIEW_ROOT USING CONFIG = {dq}{config}{dq}").collect()
    return {"ok": True, "run_id": run_id, "project_id": pid,
            "message": "started; SELECT * FROM APP.V_REVIEW_RUNS WHERE RUN_ID = '" + run_id + "'"}
$$;

-------------------------------------------------------------------------------
-- 逐次ベースライン: 同じワーカーを 1 つずつ呼び、同じ fan-in を行う（同期）。並列との比較用。
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

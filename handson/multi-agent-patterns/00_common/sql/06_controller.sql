-- 00_common/sql/06_controller.sql
-- Common foundation: package controller/src/*.py on the stage and create inspection views.
-- Run after setup.sh uploads controller/src/*.py to @<% db %>.AGENTS.APP_STAGE/lib/src/.
-- Each pattern creates its controller procedures, such as APP.RUN_*, in sql/20_procedures.sql.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- Pack @APP_STAGE/lib/src/*.py into @APP_STAGE/lib/tms_controller.zip (setup helper).
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.BUILD_CONTROLLER_ZIP()
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Setup helper: zip the uploaded controller code for the controller procedures'
EXECUTE AS OWNER
AS
$$
import io
import zipfile

from snowflake.snowpark.files import SnowflakeFile

STAGE = "@<% db %>.AGENTS.APP_STAGE"


def run(session):
    rows = session.sql(f"LIST {STAGE}/lib/src/").collect()
    names = sorted({r["name"].split("/")[-1] for r in rows if r["name"].endswith(".py")})
    if "controller.py" not in names:
        raise ValueError("Upload every file in app/src/ (not views/) to @APP_STAGE/lib/src/ first. Found: "
                         + ", ".join(names))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            with SnowflakeFile.open(f"{STAGE}/lib/src/{name}", "rb", require_scoped_url=False) as f:
                z.writestr(f"src/{name}", f.read())
    buf.seek(0)
    session.file.put_stream(buf, f"{STAGE}/lib/tms_controller.zip", auto_compress=False, overwrite=True)
    return {"ok": True, "files": names}
$$;

-- Fails loudly (and stops setup) when the controller files were not uploaded.
CALL <% db %>.AGENTS.BUILD_CONTROLLER_ZIP();

-------------------------------------------------------------------------------
-- Inspection views for the proposal queue, trace, and task board.
-------------------------------------------------------------------------------
CREATE OR REPLACE VIEW <% db %>.APP.V_REVIEW_QUEUE
COMMENT = 'Proposed actions with their latest verification result'
AS
SELECT a.ACTION_ID, a.RUN_ID, a.STATUS, a.ACTION_TYPE, a.TARGET_TASK_ID,
       a.PAYLOAD:title::STRING AS TITLE, a.RISK_LEVEL, a.CONFIDENCE,
       v.FINAL_STATUS AS VERIFICATION, v.ISSUES AS VERIFICATION_ISSUES,
       a.EVIDENCE[0]:quote::STRING AS EVIDENCE_QUOTE, a.REASON, a.CREATED_AT
FROM <% db %>.INTERNAL.PROPOSED_ACTIONS a
LEFT JOIN <% db %>.INTERNAL.VERIFICATION_RESULTS v
  ON v.ACTION_ID = a.ACTION_ID
QUALIFY ROW_NUMBER() OVER (PARTITION BY a.ACTION_ID ORDER BY v.CREATED_AT DESC NULLS LAST) = 1;

CREATE OR REPLACE VIEW <% db %>.APP.V_RUN_TRACE
COMMENT = 'Application-level multi-agent trace (one row per controller step)'
AS
SELECT RUN_ID, STEP_NO, PATTERN, AGENT_NAME, STATUS, ELAPSED_MS,
       INPUT_SUMMARY, OUTPUT_SUMMARY, CREATED_AT
FROM <% db %>.INTERNAL.RUN_EVENTS;

CREATE OR REPLACE VIEW <% db %>.APP.V_TASK_BOARD
COMMENT = 'Current task board'
AS
SELECT t.TASK_ID, t.PROJECT_ID, p.PROJECT_NAME, t.TITLE, t.STATUS, t.PRIORITY, t.ASSIGNEE, t.DUE_DATE,
       (t.DUE_DATE < CURRENT_DATE() AND t.STATUS <> 'DONE') AS OVERDUE,
       t.SOURCE_TYPE, t.SOURCE_REF, t.UPDATED_AT
FROM <% db %>.APP.TASKS t
LEFT JOIN <% db %>.APP.PROJECTS p ON p.PROJECT_ID = t.PROJECT_ID;

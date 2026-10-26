-- 02_orchestrator_worker/sql/20_procedures.sql
-- コントローラプロシージャ（呼び出し元権限）: Decomposer → APP.WORKER_PLAN の Worker → 集約。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- Orchestrator/Worker: decomposer -> dedupe + criteria workers -> aggregated proposals.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.RUN_MEETING_NOTE(NOTE_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Orchestrator/Worker: decompose one meeting note into proposed actions'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, note_id):
    return controller.process_note(session, Config("<% db %>"), note_id)
$$;


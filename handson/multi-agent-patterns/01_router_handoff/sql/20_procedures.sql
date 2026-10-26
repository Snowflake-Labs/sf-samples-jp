-- 01_router_handoff/sql/20_procedures.sql
-- コントローラプロシージャ（呼び出し元権限）: ルーター → 専門エージェント 1 つ（または人間）。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- Router/Handoff: router -> one specialist (or human). Proposals stay PROPOSED.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.RUN_INBOX_REQUEST(REQUEST_TEXT STRING, PROJECT_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Router/Handoff: route one inbox request and hand off to a specialist agent'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, request_text, project_id):
    if not (request_text or "").strip():
        return {"error": "REQUEST_TEXT is empty"}
    return controller.handle_request(session, Config("<% db %>"), request_text, project_id or "PRJ-PORTAL")
$$;


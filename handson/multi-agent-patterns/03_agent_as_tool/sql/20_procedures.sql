-- 03_agent_as_tool/sql/20_procedures.sql
-- エージェントからエージェントを呼ぶラッパー（所有者権限、呼び先は固定）と、
-- オーケストレーターエージェントの返答を検証して提案に保存するコントローラプロシージャ。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- ASK_DECOMPOSER_WORKER: run the TMS_DECOMPOSER_AGENT worker with one request (no side effects)
-- Agent-to-agent through a wrapper procedure: an agent cannot call another agent directly, so the
-- orchestrator agent gets this procedure as a custom tool. The worker is fixed here (no agent name
-- parameter), so the tool can reach only this worker; the worker keeps its own instructions and tools.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.ASK_DECOMPOSER_WORKER(REQUEST STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Worker call: send one request to TMS_DECOMPOSER_AGENT (candidates from a meeting note) and return its reply'
EXECUTE AS OWNER
AS
$$
import json

AGENT = "<% db %>.AGENTS.TMS_DECOMPOSER_AGENT"


def run(session, request):
    request = (request or "")[:20000]
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": request}]}]})
    try:
        raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
        resp = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return json.dumps({"error": str(exc)[:300]})
    text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if c.get("type") == "text").strip()
    return text or json.dumps({"error": (resp or {}).get("message", "worker returned no text")})
$$;

-------------------------------------------------------------------------------
-- ASK_DEDUPE_WORKER: run the TMS_DEDUPE_AGENT worker with one request (no side effects)
-- Agent-to-agent through a wrapper procedure: an agent cannot call another agent directly, so the
-- orchestrator agent gets this procedure as a custom tool. The worker is fixed here (no agent name
-- parameter), so the tool can reach only this worker; the worker keeps its own instructions and tools.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.ASK_DEDUPE_WORKER(REQUEST STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Worker call: send one request to TMS_DEDUPE_AGENT (create, link, or skip per candidate) and return its reply'
EXECUTE AS OWNER
AS
$$
import json

AGENT = "<% db %>.AGENTS.TMS_DEDUPE_AGENT"


def run(session, request):
    request = (request or "")[:20000]
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": request}]}]})
    try:
        raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
        resp = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return json.dumps({"error": str(exc)[:300]})
    text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if c.get("type") == "text").strip()
    return text or json.dumps({"error": (resp or {}).get("message", "worker returned no text")})
$$;

-------------------------------------------------------------------------------
-- ASK_CRITERIA_WORKER: run the TMS_CRITERIA_AGENT worker with one request (no side effects)
-- Agent-to-agent through a wrapper procedure: an agent cannot call another agent directly, so the
-- orchestrator agent gets this procedure as a custom tool. The worker is fixed here (no agent name
-- parameter), so the tool can reach only this worker; the worker keeps its own instructions and tools.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.ASK_CRITERIA_WORKER(REQUEST STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Worker call: send one request to TMS_CRITERIA_AGENT (titles and acceptance criteria) and return its reply'
EXECUTE AS OWNER
AS
$$
import json

AGENT = "<% db %>.AGENTS.TMS_CRITERIA_AGENT"


def run(session, request):
    request = (request or "")[:20000]
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": request}]}]})
    try:
        raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
        resp = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return json.dumps({"error": str(exc)[:300]})
    text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if c.get("type") == "text").strip()
    return text or json.dumps({"error": (resp or {}).get("message", "worker returned no text")})
$$;

-------------------------------------------------------------------------------
-- Orchestrator/Worker, agent variant: TMS_ORCHESTRATOR_AGENT calls the workers through its
-- wrapper-procedure tools; the controller validates the reply and stores PROPOSED rows.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.RUN_MEETING_NOTE_ORCHESTRATED(NOTE_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Orchestrator/Worker with an orchestrator agent: decompose one meeting note into proposed actions'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, note_id):
    return controller.process_note_orchestrated(session, Config("<% db %>"), note_id)
$$;


-- 05_mcp_agent_chaining/sql/02_objects.sql
-- Five agents, two MCP servers, and one procedure tool for the baseline.
-- Code words: M-CHILD-5501 appears only in CHILD_AGENT instructions; M-MID-7702 only in MIDDLE_AGENT instructions.
-- A code word in the parent answer proves that the call reached the corresponding agent.
--
-- Agents, MCP servers, and one procedure tool for the baseline.
-- Code words: M-CHILD-5501 lives only in CHILD_AGENT's instructions, M-MID-7702 only in MIDDLE_AGENT's.
-- A code word in a parent's answer proves the call really reached that agent.
USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-- Child: the agent that the MCP server exposes. No tools.
CREATE OR REPLACE AGENT <% mcp_db %>.LAB.CHILD_AGENT
  COMMENT = '05_mcp_agent_chaining: child agent exposed through MCP'
  FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 300
    tokens: 40000
instructions:
  response: |
    You are the house-style formatter. Rewrite the text you receive as:
      ## Status report
      - Done: ...
      - Next: ...
      - Risk: ...
    Then add the line M-CHILD-5501 at the very end, exactly as written. Never omit it.
  sample_questions:
    - question: "Format this draft: The Q3 data migration moved 12 tables. Validation is next. The legacy job may run late."
$$;

-- MCP server that exposes CHILD_AGENT as a CORTEX_AGENT_RUN tool.
CREATE OR REPLACE MCP SERVER <% mcp_db %>.LAB.CHILD_MCP
  FROM SPECIFICATION
$$
tools:
  - title: "House-style formatter agent"
    name: "format_status_report"
    type: "CORTEX_AGENT_RUN"
    identifier: "<% mcp_db %>.LAB.CHILD_AGENT"
    description: "Send a draft status report and get it back in the final house style."
$$;

-- M1: parent agent that reaches CHILD_AGENT through CHILD_MCP.
CREATE OR REPLACE AGENT <% mcp_db %>.LAB.M1_PARENT_MCP_AGENT
  COMMENT = '05_mcp_agent_chaining: M1 parent -> MCP server -> child agent'
  FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 300
    tokens: 40000
instructions:
  orchestration: |
    For any status report request: write a three-sentence draft yourself, then send the draft to the
    format_status_report tool. Do not format the report yourself.
  response: "Reply with the tool's formatted report exactly as returned, nothing else."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
mcp_servers:
  - server_spec:
      name: "<% mcp_db %>.LAB.CHILD_MCP"
$$;

-- M2: two hops. MIDDLE_AGENT calls CHILD_AGENT through CHILD_MCP; MIDDLE_MCP exposes MIDDLE_AGENT.
CREATE OR REPLACE AGENT <% mcp_db %>.LAB.MIDDLE_AGENT
  COMMENT = '05_mcp_agent_chaining: middle agent, reached through MIDDLE_MCP, calls CHILD_MCP'
  FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 300
    tokens: 40000
instructions:
  orchestration: |
    Send the text you receive to the format_status_report tool. Do not format it yourself.
  response: |
    Start your reply with the line M-MID-7702, exactly as written. Then copy the tool's formatted
    report exactly as returned.
mcp_servers:
  - server_spec:
      name: "<% mcp_db %>.LAB.CHILD_MCP"
$$;

CREATE OR REPLACE MCP SERVER <% mcp_db %>.LAB.MIDDLE_MCP
  FROM SPECIFICATION
$$
tools:
  - title: "Report reviewer agent"
    name: "review_status_report"
    type: "CORTEX_AGENT_RUN"
    identifier: "<% mcp_db %>.LAB.MIDDLE_AGENT"
    description: "Send a draft status report and get back the reviewed, house-style version."
$$;

CREATE OR REPLACE AGENT <% mcp_db %>.LAB.M2_PARENT_TWO_HOP_AGENT
  COMMENT = '05_mcp_agent_chaining: M2 parent -> MIDDLE_MCP -> middle agent -> CHILD_MCP -> child agent'
  FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 300
    tokens: 40000
instructions:
  orchestration: |
    For any status report request: write a three-sentence draft yourself, then send the draft to the
    review_status_report tool. Do not format the report yourself.
  response: "Reply with the tool's reply exactly as returned, nothing else."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
mcp_servers:
  - server_spec:
      name: "<% mcp_db %>.LAB.MIDDLE_MCP"
$$;

-- M3 baseline: the same child reached through a procedure tool (the pattern 03 approach).
CREATE OR REPLACE PROCEDURE <% mcp_db %>.LAB.ASK_CHILD_AGENT(REQUEST STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = '05_mcp_agent_chaining: send one request to CHILD_AGENT and return only its text reply'
EXECUTE AS OWNER
AS
$$
import json

AGENT = "<% mcp_db %>.LAB.CHILD_AGENT"


def run(session, request):
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": (request or "")[:20000]}]}]})
    try:
        raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
        resp = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return json.dumps({"error": str(exc)[:300]})
    text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if c.get("type") == "text").strip()
    return text or json.dumps({"error": (resp or {}).get("message", "child agent returned no text")})
$$;

CREATE OR REPLACE AGENT <% mcp_db %>.LAB.M3_PARENT_PROCEDURE_AGENT
  COMMENT = '05_mcp_agent_chaining: M3 baseline, parent -> procedure tool -> child agent'
  FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 300
    tokens: 40000
instructions:
  orchestration: |
    For any status report request: write a three-sentence draft yourself, then send the draft to the
    format_status_report tool. Do not format the report yourself.
  response: "Reply with the tool's formatted report exactly as returned, nothing else."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
tools:
  - tool_spec:
      type: generic
      name: format_status_report
      description: "Send a draft status report and get it back in the final house style."
      input_schema:
        type: object
        properties:
          request:
            type: string
            description: "The draft status report text"
        required: [request]
tool_resources:
  format_status_report:
    type: procedure
    identifier: <% mcp_db %>.LAB.ASK_CHILD_AGENT
    execution_environment:
      type: warehouse
      warehouse: <% wh %>
      query_timeout: 180
$$;

SHOW AGENTS IN SCHEMA <% mcp_db %>.LAB;
SHOW MCP SERVERS IN SCHEMA <% mcp_db %>.LAB;

-- 06_skill_composition/sql/02_agents.sql
-- Six agents (P0-P4 plus FORMATTER_AGENT) and the procedure tool used by P4.
-- Skill bodies are at @<% skill_db %>.LAB.SKILL_STAGE/skills/<name>/SKILL.md, uploaded by setup.sh.
-- Code words: P-ALPHA-3141 appears only in the parent skill body; C-BRAVO-2718 only in the child style skill.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.P0_CONTROL_AGENT
    COMMENT = '06_skill_composition: control: child-formatter only'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Format this draft status report: The Q3 data migration moved 12 tables. Validation is next. The legacy job may run late."
    - question: "Format this draft: The new dashboard is live. User training starts Monday. Budget approval is still pending."
skills:
  - name: child-formatter
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/child-formatter"
$$;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.P1_PEER_AGENT
    COMMENT = '06_skill_composition: parent and child registered as peer skills'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
skills:
  - name: parent-report
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/parent-report"
  - name: child-formatter
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/child-formatter"
$$;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.P2_NESTED_AGENT
    COMMENT = '06_skill_composition: parent only; child SKILL.md in a subfolder'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
skills:
  - name: parent-nested
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/parent-nested"
$$;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.P3_COMBINED_AGENT
    COMMENT = '06_skill_composition: one skill containing both steps'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
skills:
  - name: combined-report
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/combined-report"
$$;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.FORMATTER_AGENT
    COMMENT = '06_skill_composition: sub-agent that owns child-formatter'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Format this draft status report: The Q3 data migration moved 12 tables. Validation is next. The legacy job may run late."
skills:
  - name: child-formatter
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/child-formatter"
$$;

CREATE OR REPLACE PROCEDURE <% skill_db %>.LAB.ASK_FORMATTER_AGENT(REQUEST STRING)
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = '06_skill_composition: send one request to FORMATTER_AGENT and return its text reply'
EXECUTE AS OWNER
AS
$$
import json

AGENT = "<% skill_db %>.LAB.FORMATTER_AGENT"


def run(session, request):
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": (request or "")[:20000]}]}]})
    try:
        raw = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R", params=[AGENT, body]).collect()[0]["R"]
        resp = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as exc:
        return json.dumps({"error": str(exc)[:300]})
    text = "".join(c.get("text", "") for c in (resp or {}).get("content") or [] if c.get("type") == "text").strip()
    return text or json.dumps({"error": (resp or {}).get("message", "sub-agent returned no text")})
$$;

CREATE OR REPLACE AGENT <% skill_db %>.LAB.P4_SUBAGENT_AGENT
    COMMENT = '06_skill_composition: parent skill delegates to FORMATTER_AGENT through a procedure tool'
    FROM SPECIFICATION
$$
models:
  orchestration: auto
orchestration:
  budget:
    seconds: 120
    tokens: 16000
instructions:
  response: "Answer in English. Use the configured skills when they are relevant."
  sample_questions:
    - question: "Write a status report about the Q3 data migration project."
    - question: "Write a status report about the customer portal redesign."
skills:
  - name: parent-delegate
    source:
      type: STAGE
      path: "@<% skill_db %>.LAB.SKILL_STAGE/skills/parent-delegate"
tools:
  - tool_spec:
      type: generic
      name: ask_formatter_agent
      description: "Send a draft status report to the formatter agent and return the report in the final house style."
      input_schema:
        type: object
        properties:
          request:
            type: string
            description: "The draft status report text"
        required: [request]
tool_resources:
  ask_formatter_agent:
    type: procedure
    identifier: <% skill_db %>.LAB.ASK_FORMATTER_AGENT
    execution_environment:
      type: warehouse
      warehouse: <% wh %>
      query_timeout: 180
$$;

SHOW AGENTS IN SCHEMA <% skill_db %>.LAB;

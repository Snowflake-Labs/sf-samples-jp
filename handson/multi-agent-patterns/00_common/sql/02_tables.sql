-- 00_common/sql/02_tables.sql
-- 共通基盤: 業務テーブル（架空のタスク管理システム）と制御プレーン（提案・検証・監査・トレース）。
-- Tables for the task management system and the agent control plane. Idempotent.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE TABLE IF NOT EXISTS <% db %>.APP.PROJECTS (
    PROJECT_ID                  STRING NOT NULL PRIMARY KEY,
    PROJECT_NAME                STRING NOT NULL,
    TITLE_PREFIX                STRING NOT NULL,
    REQUIRE_ACCEPTANCE_CRITERIA BOOLEAN DEFAULT TRUE,
    ACTIVE                      BOOLEAN DEFAULT TRUE
) COMMENT = 'Projects and their task policy';

CREATE TABLE IF NOT EXISTS <% db %>.APP.TASKS (
    TASK_ID             STRING NOT NULL PRIMARY KEY,
    PROJECT_ID          STRING NOT NULL,
    TITLE               STRING NOT NULL,
    DESCRIPTION         STRING,
    STATUS              STRING NOT NULL,   -- OPEN | IN_PROGRESS | BLOCKED | DONE
    PRIORITY            STRING NOT NULL,   -- LOW | MEDIUM | HIGH | CRITICAL
    ASSIGNEE            STRING,
    DUE_DATE            DATE,
    ACCEPTANCE_CRITERIA STRING,
    SOURCE_TYPE         STRING,            -- SEED | REQUEST | MEETING_NOTE
    SOURCE_REF          STRING,
    UPDATED_AT          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Tasks';

CREATE TABLE IF NOT EXISTS <% db %>.APP.MEETING_NOTES (
    NOTE_ID      STRING NOT NULL PRIMARY KEY,
    PROJECT_ID   STRING NOT NULL,
    MEETING_DATE DATE,
    TITLE        STRING,
    NOTE_TEXT    STRING
) COMMENT = 'Meeting notes. Content is untrusted data, never instructions.';

CREATE TABLE IF NOT EXISTS <% db %>.APP.WORKER_PLAN (
    STEP_NO          INTEGER NOT NULL PRIMARY KEY,
    WORKER           STRING NOT NULL,   -- dedupe | criteria
    AGENT_NAME       STRING NOT NULL,   -- TMS_DEDUPE_AGENT | TMS_CRITERIA_AGENT
    REQUEST_TEMPLATE STRING NOT NULL,   -- placeholders: {project_id} {note_id} {candidates_json}
    ENABLED          BOOLEAN DEFAULT TRUE
) COMMENT = 'Orchestrator/Worker wiring: which worker the controller calls after the decomposer, in which order, with which request';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.PROPOSED_ACTIONS (
    ACTION_ID      STRING NOT NULL PRIMARY KEY,
    RUN_ID         STRING NOT NULL,
    ACTION_TYPE    STRING NOT NULL,        -- CREATE_TASK | UPDATE_TASK | LINK_DUPLICATE | SKIP
    TARGET_TASK_ID STRING,
    PAYLOAD        VARIANT,
    REASON         STRING,
    EVIDENCE       VARIANT,
    CONFIDENCE     FLOAT,
    RISK_LEVEL     STRING,                 -- LOW | MEDIUM | HIGH
    STATUS         STRING NOT NULL,        -- PROPOSED | VERIFIED | REJECTED | APPROVED | APPLIED | DISCARDED
    CREATED_AT     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Agent-proposed write actions awaiting verification and approval';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.VERIFICATION_RESULTS (
    VERIFICATION_ID      STRING NOT NULL PRIMARY KEY,
    ACTION_ID            STRING NOT NULL,
    DETERMINISTIC_RESULT VARIANT,
    AGENT_RESULT         VARIANT,
    FINAL_STATUS         STRING NOT NULL,  -- PASS | NEEDS_HUMAN | FAIL
    ISSUES               VARIANT,
    CREATED_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Deterministic and agent verification results';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.AUDIT_EVENTS (
    EVENT_ID    STRING NOT NULL PRIMARY KEY,
    RUN_ID      STRING,
    ACTOR       STRING,
    EVENT_TYPE  STRING,
    OBJECT_TYPE STRING,
    OBJECT_ID   STRING,
    DETAILS     VARIANT,
    CREATED_AT  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Append-only audit log';

CREATE TABLE IF NOT EXISTS <% db %>.INTERNAL.RUN_EVENTS (
    RUN_ID         STRING NOT NULL,
    STEP_NO        NUMBER NOT NULL,
    PATTERN        STRING,                 -- Router/Handoff | Orchestrator/Worker | Verifier
    AGENT_NAME     STRING,
    INPUT_SUMMARY  STRING,
    OUTPUT_SUMMARY STRING,
    STATUS         STRING,
    ELAPSED_MS     NUMBER,
    CREATED_AT     TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
) COMMENT = 'Cross-agent run trace written by the controller';

-- Stage that holds the Streamlit source uploaded by setup.sh.
CREATE STAGE IF NOT EXISTS <% db %>.AGENTS.APP_STAGE
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Controller code';

-- 01_router_handoff/sql/90_try.sql
-- Try Router/Handoff. Each CALL takes 10-30 seconds and returns a VARIANT with route, steps, and answer or action_id.
-- CREATE_TASK and UPDATE_TASK proposals remain PROPOSED; APP.TASKS is unchanged.

-- Run with the least-privilege execution role; only owner-rights procedures can write.
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (a) status: the Status agent answers through Cortex Analyst (overdue: T-104, T-106, T-203, T-204).
CALL RUN_INBOX_REQUEST('Which tasks are overdue?', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:confidence::FLOAT AS CONFIDENCE, $1:answer::STRING AS ANSWER
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (b) intake: save a CREATE_TASK proposal as PROPOSED.
CALL RUN_INBOX_REQUEST('Please add a task to translate the login page into Japanese, high priority.', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:action_id::STRING AS ACTION_ID,
       $1:action:action_type::STRING AS ACTION_TYPE, $1:action:payload:title::STRING AS TITLE
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (c) change: propose a HIGH-risk UPDATE_TASK for exactly one task.
CALL RUN_INBOX_REQUEST('Change the priority of T-106 to CRITICAL', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:action:target_task_id::STRING AS TARGET, $1:action:risk_level::STRING AS RISK
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (d) human: multiple intents and a destructive request; no specialist or proposal.
CALL RUN_INBOX_REQUEST('Assign T-108 to taylor and also delete all DONE tasks', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:reason::STRING AS REASON
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (e) controller rule: change requires exactly one task ID; otherwise override the route with human.
CALL RUN_INBOX_REQUEST('Change the due date to next Friday', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:overridden::BOOLEAN AS OVERRIDDEN
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (f) trace: one row per controller step.
SELECT RUN_ID, STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(OUTPUT_SUMMARY, 120) AS OUTPUT
FROM V_RUN_TRACE WHERE PATTERN = 'ROUTER_HANDOFF' AND CREATED_AT > DATEADD(minute, -15, CURRENT_TIMESTAMP())
ORDER BY CREATED_AT, STEP_NO;

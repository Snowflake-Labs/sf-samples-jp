-- 02_orchestrator_worker/sql/90_try.sql
-- Try the controller-based Orchestrator/Worker pattern. One run takes 30-90 seconds.
-- N-003 contains an "IGNORE ALL PREVIOUS INSTRUCTIONS ..." injection line; verify that it is not a candidate.

-- Run with the least-privilege execution role; only owner-rights procedures can write.
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- Wiring: workers called by the controller after Decomposer, including order and request templates.
SELECT STEP_NO, WORKER, AGENT_NAME, ENABLED FROM WORKER_PLAN ORDER BY STEP_NO;

CALL RUN_MEETING_NOTE('N-003');
SET note_qid = LAST_QUERY_ID();

-- Expected proposals: CREATE_TASK with a [PORTAL] title and LINK_DUPLICATE to existing task T-108.
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, a.value:payload:acceptance_criteria::STRING AS CRITERIA,
       a.value:evidence[0]:quote::STRING AS QUOTE
FROM TABLE(RESULT_SCAN($note_qid)) r, LATERAL FLATTEN(r.$1:actions) a;

-- Trace: the controller called the workers; compare with pattern 03.
SELECT STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(OUTPUT_SUMMARY, 200) AS OUTPUT
FROM V_RUN_TRACE WHERE RUN_ID = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN($note_qid)))
ORDER BY STEP_NO;

-- 03_agent_as_tool/sql/90_try.sql
-- Try the agent-based Orchestrator/Worker pattern. One run takes 60-120 seconds.
-- TMS_ORCHESTRATOR_AGENT calls workers through ASK_*_WORKER tools; the controller only validates the response.

-- Run with the least-privilege execution role; only owner-rights procedures can write.
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

CALL RUN_MEETING_NOTE_ORCHESTRATED('N-003');
SET orch_qid = LAST_QUERY_ID();

-- Expected proposals match pattern 02: CREATE_TASK and LINK_DUPLICATE to T-108.
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, a.value:evidence[0]:quote::STRING AS QUOTE
FROM TABLE(RESULT_SCAN($orch_qid)) r, LATERAL FLATTEN(r.$1:actions) a;

-- Trace: the controller sees one orchestrator step and its tool calls.
-- Inspect worker internals in Snowsight > AI & ML > Agents > each worker > Monitoring.
SELECT STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(INPUT_SUMMARY, 300) AS INPUT, LEFT(OUTPUT_SUMMARY, 200) AS OUTPUT
FROM V_RUN_TRACE WHERE RUN_ID = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN($orch_qid)))
ORDER BY STEP_NO;

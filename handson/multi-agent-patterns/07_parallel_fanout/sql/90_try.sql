-- 07_parallel_fanout/sql/90_try.sql
-- Try parallel fan-out/fan-in. The parallel run is asynchronous (20-30 seconds); the sequential baseline is synchronous.

-- Run with the least-privilege execution role; only owner-rights procedures can write.
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (1) Parallel: start the task graph and return RUN_ID.
CALL START_PROJECT_REVIEW('PRJ-PORTAL');
SET par_run = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));

-- Re-run every few dozen seconds until STATUS changes from RUNNING to DONE.
SELECT RUN_ID, MODE, STATUS, TOTAL_SECONDS, TASKS_FLAGGED, BY_SEVERITY FROM V_REVIEW_RUNS WHERE RUN_ID = $par_run;

-- Inspect worker start and finish times; concurrent workers have nearly identical STARTED_AT values.
SELECT PERSPECTIVE, STATUS, STARTED_AT, FINISHED_AT, SECONDS, FINDINGS FROM V_REVIEW_WORKERS
WHERE RUN_ID = $par_run ORDER BY STARTED_AT;

-- (2) Sequential baseline: call the same three workers in order and return the report synchronously.
CALL RUN_PROJECT_REVIEW_SEQUENTIAL('PRJ-PORTAL');

-- (3) Compare parallel and sequential duration and finding counts.
SELECT RUN_ID, MODE, STATUS, TOTAL_SECONDS, TASKS_FLAGGED, BY_SEVERITY FROM V_REVIEW_RUNS
ORDER BY STARTED_AT DESC LIMIT 4;

-- (4) Inspect the aggregated report from the latest parallel run.
SELECT i.value:task_id::STRING AS TASK_ID, i.value:severity::STRING AS SEVERITY,
       ARRAY_TO_STRING(i.value:perspectives, ', ') AS PERSPECTIVES, i.value:issues[0]:issue::STRING AS FIRST_ISSUE
FROM V_REVIEW_RUNS r, LATERAL FLATTEN(r.REPORT:items) i
WHERE r.RUN_ID = $par_run ORDER BY i.index;

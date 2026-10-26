-- 00_common/sql/09_smoke_tests.sql
-- LLM を呼ばない決定論的チェック。どれかが失敗すると最後の文がゼロ除算で失敗し、setup.sh が止まる。

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.INTERNAL;

CALL <% db %>.AGENTS.GET_TASK('T-104');
SET get_task_ok = (SELECT $1:found::BOOLEAN AND $1:status::STRING = 'BLOCKED' FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
CALL <% db %>.AGENTS.VALIDATE_PROPOSED_ACTION('{"action_type":"CREATE_TASK","payload":{"project_id":"PRJ-PORTAL","title":"No prefix","priority":"HIGH"},"evidence":[]}');
SET bad_action_rejected = (SELECT NOT $1:passed::BOOLEAN FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
CALL <% db %>.AGENTS.VALIDATE_PROPOSED_ACTION('{"action_type":"UPDATE_TASK","target_task_id":"T-106","payload":{"priority":"HIGH"},"reason":"smoke","evidence":[{"source_type":"REQUEST","source_id":"smoke","quote":"smoke"}]}');
SET good_action_passes = (SELECT $1:passed::BOOLEAN FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
CALL <% db %>.INTERNAL.APPLY_APPROVED_ACTION('DOES-NOT-EXIST', 'smoke');
SET apply_guarded = (SELECT NOT $1:ok::BOOLEAN FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
LIST @<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip;
SET zip_built = (SELECT COUNT(*) = 1 FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));

CREATE OR REPLACE TEMPORARY TABLE SMOKE_RESULTS AS
SELECT 'projects_seeded' AS CHECK_NAME, ((SELECT COUNT(*) FROM <% db %>.APP.PROJECTS) >= 2) AS PASSED
UNION ALL SELECT 'tasks_seeded', ((SELECT COUNT(*) FROM <% db %>.APP.TASKS WHERE SOURCE_TYPE = 'SEED') = 14)
UNION ALL SELECT 'notes_seeded', ((SELECT COUNT(*) FROM <% db %>.APP.MEETING_NOTES) >= 3)
UNION ALL SELECT 'overdue_examples', ((SELECT COUNT(*) FROM <% db %>.APP.TASKS WHERE DUE_DATE < CURRENT_DATE() AND STATUS <> 'DONE') >= 3)
UNION ALL SELECT 'semantic_view_queryable', ((SELECT COUNT(*) FROM SEMANTIC_VIEW(<% db %>.AGENTS.TMS_SEMANTIC_VIEW METRICS tasks.task_count)) = 1)
UNION ALL SELECT 'views', ((SELECT COUNT(*) FROM <% db %>.INFORMATION_SCHEMA.VIEWS
    WHERE TABLE_SCHEMA = 'APP' AND TABLE_NAME IN ('V_REVIEW_QUEUE', 'V_RUN_TRACE', 'V_TASK_BOARD')) = 3)
UNION ALL SELECT 'controller_zip', ($zip_built)
UNION ALL SELECT 'get_task_tool', ($get_task_ok)
UNION ALL SELECT 'validation_rejects_bad', ($bad_action_rejected)
UNION ALL SELECT 'validation_passes_good', ($good_action_passes)
UNION ALL SELECT 'apply_requires_approval', ($apply_guarded);

SELECT CHECK_NAME, IFF(PASSED, 'PASS', 'FAIL') AS RESULT FROM SMOKE_RESULTS ORDER BY CHECK_NAME;
SELECT 1 / IFF(COUNT_IF(NOT PASSED) = 0, 1, 0) AS SMOKE_TESTS_PASSED FROM SMOKE_RESULTS;

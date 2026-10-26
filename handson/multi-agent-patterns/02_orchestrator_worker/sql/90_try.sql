-- 02_orchestrator_worker/sql/90_try.sql
-- Orchestrator/Worker（コントローラ型）を試す。1 回 30〜90 秒。
-- N-003 には「IGNORE ALL PREVIOUS INSTRUCTIONS ...」という注入行がある。候補にならないことを確認する。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- 配線: コントローラが Decomposer の後に呼ぶ Worker（順番と依頼テンプレート）
SELECT STEP_NO, WORKER, AGENT_NAME, ENABLED FROM WORKER_PLAN ORDER BY STEP_NO;

CALL RUN_MEETING_NOTE('N-003');
SET note_qid = LAST_QUERY_ID();

-- 提案: CREATE_TASK（[PORTAL] 付きタイトル）と、既存 T-108 への LINK_DUPLICATE が期待値
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, a.value:payload:acceptance_criteria::STRING AS CRITERIA,
       a.value:evidence[0]:quote::STRING AS QUOTE
FROM TABLE(RESULT_SCAN($note_qid)) r, LATERAL FLATTEN(r.$1:actions) a;

-- トレース: Worker を呼んだのはコントローラ（パターン 03 と比較する）
SELECT STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(OUTPUT_SUMMARY, 200) AS OUTPUT
FROM V_RUN_TRACE WHERE RUN_ID = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN($note_qid)))
ORDER BY STEP_NO;

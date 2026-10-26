-- 03_agent_as_tool/sql/90_try.sql
-- Orchestrator/Worker（エージェント型）を試す。1 回 60〜120 秒。
-- TMS_ORCHESTRATOR_AGENT が ASK_*_WORKER ツール経由で Worker エージェントを呼び、コントローラは返答を検証するだけ。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

CALL RUN_MEETING_NOTE_ORCHESTRATED('N-003');
SET orch_qid = LAST_QUERY_ID();

-- 提案: パターン 02 と同じ 2 件（CREATE_TASK と T-108 への LINK_DUPLICATE）が期待値
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, a.value:evidence[0]:quote::STRING AS QUOTE
FROM TABLE(RESULT_SCAN($orch_qid)) r, LATERAL FLATTEN(r.$1:actions) a;

-- トレース: コントローラから見えるのはオーケストレーターの 1 ステップとそのツール呼び出し。
-- Worker 内部の詳細は Snowsight > AI & ML > Agents > 各 Worker > Monitoring（Observability）で確認する。
SELECT STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(INPUT_SUMMARY, 300) AS INPUT, LEFT(OUTPUT_SUMMARY, 200) AS OUTPUT
FROM V_RUN_TRACE WHERE RUN_ID = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN($orch_qid)))
ORDER BY STEP_NO;

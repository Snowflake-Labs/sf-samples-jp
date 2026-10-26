-- 01_router_handoff/sql/90_try.sql
-- Router/Handoff を試す。各 CALL は 10〜30 秒。結果は VARIANT（route, steps, answer または action_id）。
-- 提案（CREATE_TASK / UPDATE_TASK）は PROPOSED のまま保存され、APP.TASKS は変わらない。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (a) status: Status エージェントが Cortex Analyst で読み取り回答する（期限切れ: T-104, T-106, T-203, T-204）
CALL RUN_INBOX_REQUEST('Which tasks are overdue?', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:confidence::FLOAT AS CONFIDENCE, $1:answer::STRING AS ANSWER
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (b) intake: CREATE_TASK の提案が PROPOSED で保存される
CALL RUN_INBOX_REQUEST('Please add a task to translate the login page into Japanese, high priority.', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:action_id::STRING AS ACTION_ID,
       $1:action:action_type::STRING AS ACTION_TYPE, $1:action:payload:title::STRING AS TITLE
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (c) change: 1 タスクだけの UPDATE_TASK 提案（HIGH リスク）
CALL RUN_INBOX_REQUEST('Change the priority of T-106 to CRITICAL', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:action:target_task_id::STRING AS TARGET, $1:action:risk_level::STRING AS RISK
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (d) human: 複数意図・破壊的な依頼。専門エージェントは呼ばれず、提案も作られない
CALL RUN_INBOX_REQUEST('Assign T-108 to taylor and also delete all DONE tasks', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:reason::STRING AS REASON
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (e) コントローラのルール: change にはタスク ID がちょうど 1 つ必要。無ければ human に上書きされる
CALL RUN_INBOX_REQUEST('Change the due date to next Friday', 'PRJ-PORTAL');
SELECT $1:route:route::STRING AS ROUTE, $1:route:overridden::BOOLEAN AS OVERRIDDEN
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));

-- (f) トレース: コントローラのステップごとに 1 行
SELECT RUN_ID, STEP_NO, AGENT_NAME, STATUS, ELAPSED_MS, LEFT(OUTPUT_SUMMARY, 120) AS OUTPUT
FROM V_RUN_TRACE WHERE PATTERN = 'ROUTER_HANDOFF' AND CREATED_AT > DATEADD(minute, -15, CURRENT_TIMESTAMP())
ORDER BY CREATED_AT, STEP_NO;

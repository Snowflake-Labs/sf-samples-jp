-- 04_verifier_human_in_the_loop/sql/90_try.sql
-- Verifier + 人間承認を試す。提案は「どのエージェントが作ったか」に依らず同じゲートを通る。
-- ここでは他パターンに依存しないよう、提案を INSERT で直接作る（エージェントの提案と同じ形式）。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- 準備: 良い提案 1 件（CREATE_TASK）と HIGH リスクの変更 1 件（UPDATE_TASK）
SET run_id = (SELECT 'TRY-' || UUID_STRING());
SET good_id = (SELECT 'A-' || UUID_STRING());
SET risky_id = (SELECT 'A-' || UUID_STRING());
INSERT INTO <% db %>.INTERNAL.PROPOSED_ACTIONS
    (ACTION_ID, RUN_ID, ACTION_TYPE, TARGET_TASK_ID, PAYLOAD, REASON, EVIDENCE, CONFIDENCE, RISK_LEVEL, STATUS)
SELECT $good_id, $run_id, 'CREATE_TASK', NULL,
       PARSE_JSON('{"project_id":"PRJ-PORTAL","title":"[PORTAL] Translate login page into Japanese","priority":"HIGH","acceptance_criteria":"All login page strings are shown in Japanese when the locale is ja-JP."}'),
       'The requester asked for a Japanese login page.',
       PARSE_JSON('[{"source_type":"REQUEST","source_id":"try","quote":"Please add a task to translate the login page into Japanese, high priority."}]'),
       0.9, 'LOW', 'PROPOSED'
UNION ALL
SELECT $risky_id, $run_id, 'UPDATE_TASK', 'T-106', PARSE_JSON('{"priority":"CRITICAL"}'),
       'The requester asked to raise the priority.',
       PARSE_JSON('[{"source_type":"REQUEST","source_id":"try","quote":"Change the priority of T-106 to CRITICAL"}]'),
       0.9, 'HIGH', 'PROPOSED';

-- 1. 承認前の適用は拒否される（ok = false）
CALL APPLY_PROPOSAL($good_id);

-- 2. 検証: 決定論チェック → Verifier エージェント。期待値 FINAL_STATUS = PASS, ACTION_STATUS = VERIFIED
CALL RUN_VERIFICATION($good_id);
SET verify_qid = LAST_QUERY_ID();
SELECT $1:deterministic:passed::BOOLEAN AS DETERMINISTIC_PASSED, $1:agent:verdict::STRING AS VERIFIER_VERDICT,
       $1:final_status::STRING AS FINAL_STATUS, $1:action_status::STRING AS ACTION_STATUS
FROM TABLE(RESULT_SCAN($verify_qid));
SELECT c.value:name::STRING AS CHECK_NAME, c.value:passed::BOOLEAN AS PASSED, c.value:detail::STRING AS DETAIL
FROM TABLE(RESULT_SCAN($verify_qid)) r, LATERAL FLATTEN(r.$1:deterministic:checks) c;

-- 3. 人間が承認 → 適用（新しいタスク ID が返る）。もう一度適用しても何も起きない
CALL DECIDE_PROPOSAL($good_id, 'APPROVE');
CALL APPLY_PROPOSAL($good_id);
CALL APPLY_PROPOSAL($good_id);

-- 4. HIGH リスクの変更: チェックは通っても NEEDS_HUMAN（HIGH_RISK_ACTION）。人間が破棄する
CALL RUN_VERIFICATION($risky_id);
SELECT $1:final_status::STRING AS FINAL_STATUS, $1:issues AS ISSUES FROM TABLE(RESULT_SCAN(LAST_QUERY_ID(-1)));
CALL DECIDE_PROPOSAL($risky_id, 'DISCARD');

-- 5. 監査ログとキュー
SELECT CREATED_AT, ACTOR, EVENT_TYPE, OBJECT_TYPE, OBJECT_ID FROM <% db %>.INTERNAL.AUDIT_EVENTS
WHERE RUN_ID = $run_id ORDER BY CREATED_AT;
SELECT ACTION_ID, STATUS, ACTION_TYPE, TARGET_TASK_ID, VERIFICATION FROM V_REVIEW_QUEUE
WHERE RUN_ID = $run_id;

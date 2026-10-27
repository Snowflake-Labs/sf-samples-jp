-- 08_blackboard/sql/90_try.sql
-- ブラックボードを試す。投稿は非同期で、購読者が順に反応して 1〜2 分で PROPOSALS が書かれる。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (1) 会議メモ N-003 を掲示板に投稿する（RUN_ID が返る）
CALL POST_MEETING_NOTE('N-003');
SET board_run = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));

-- (2) 掲示板のタイムライン。数十秒おきに再実行すると、NOTE → CANDIDATES → DEDUPE / CRITERIA → PROPOSALS と増えていく
SELECT CREATED_AT, KIND, PRODUCER, ITEM_ID, PARENT_ITEM_ID, N, CONSUMED_BY
FROM V_BOARD_TIMELINE WHERE RUN_ID = $board_run ORDER BY CREATED_AT;

-- (3) 受信箱: WAITING は「もう片方の結果待ち」、ERROR は失敗（LAST_ERROR に理由）
SELECT SUBSCRIBER, ITEM_ID, STATUS, ATTEMPTS, LAST_ERROR FROM V_BOARD_INBOX WHERE RUN_ID = $board_run ORDER BY UPDATED_AT;

-- (4) 最終的な提案（02 と同じく CREATE_TASK と T-108 への LINK_DUPLICATE が期待値）。
--     提案は INTERNAL.PROPOSED_ACTIONS にも PROPOSED で保存されるので、04 の RUN_VERIFICATION で検証できる
SELECT a.value:action_type::STRING AS ACTION_TYPE, a.value:target_task_id::STRING AS TARGET,
       a.value:payload:title::STRING AS TITLE, GET(PAYLOAD:action_ids, a.index)::STRING AS ACTION_ID
FROM V_BOARD_TIMELINE, LATERAL FLATTEN(PAYLOAD:actions) a
WHERE RUN_ID = $board_run AND KIND = 'PROPOSALS';

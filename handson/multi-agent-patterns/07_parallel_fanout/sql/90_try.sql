-- 07_parallel_fanout/sql/90_try.sql
-- 並列ファンアウト／ファンインを試す。(1) 並列は非同期（約 20〜30 秒後に結果）、(2) 逐次ベースラインは同期。

-- 実行ロール（最小権限）で動かす。書き込みは所有者権限プロシージャだけが行う。
USE ROLE <% role %>;
USE SECONDARY ROLES NONE;
USE WAREHOUSE <% wh %>;
USE SCHEMA <% db %>.APP;

-- (1) 並列: タスクグラフを起動（RUN_ID が返る）
CALL START_PROJECT_REVIEW('PRJ-PORTAL');
SET par_run = (SELECT $1:run_id::STRING FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));

-- 状態を確認（STATUS が RUNNING から DONE になるまで、数十秒おきに再実行する）
SELECT RUN_ID, MODE, STATUS, TOTAL_SECONDS, TASKS_FLAGGED, BY_SEVERITY FROM V_REVIEW_RUNS WHERE RUN_ID = $par_run;

-- ワーカーごとの開始・終了時刻。並列なら 3 つの STARTED_AT がほぼ同じになる
SELECT PERSPECTIVE, STATUS, STARTED_AT, FINISHED_AT, SECONDS, FINDINGS FROM V_REVIEW_WORKERS
WHERE RUN_ID = $par_run ORDER BY STARTED_AT;

-- (2) 逐次ベースライン: 同じ 3 ワーカーを順に呼ぶ（同期、レポートがそのまま返る）
CALL RUN_PROJECT_REVIEW_SEQUENTIAL('PRJ-PORTAL');

-- (3) 比較: 並列と逐次の所要時間・指摘件数
SELECT RUN_ID, MODE, STATUS, TOTAL_SECONDS, TASKS_FLAGGED, BY_SEVERITY FROM V_REVIEW_RUNS
ORDER BY STARTED_AT DESC LIMIT 4;

-- (4) 統合レポートの中身（最新の並列実行）
SELECT i.value:task_id::STRING AS TASK_ID, i.value:severity::STRING AS SEVERITY,
       ARRAY_TO_STRING(i.value:perspectives, ', ') AS PERSPECTIVES, i.value:issues[0]:issue::STRING AS FIRST_ISSUE
FROM V_REVIEW_RUNS r, LATERAL FLATTEN(r.REPORT:items) i
WHERE r.RUN_ID = $par_run ORDER BY i.index;

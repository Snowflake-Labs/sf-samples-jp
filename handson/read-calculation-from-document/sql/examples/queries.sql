-- examples/queries.sql — 生成物と評価を SQL で見る例。<% … %> は jpcalc の名前（configs/deploy.env）で置き換える。
-- 予測側（1〜4）は予測ロール、評価側（5〜6）は評価ロールで実行する（予測ロールでは評価 DB を読めない）。
-- :run_id を自分の run_id に置き換える。

-- 1. run の状態と段ごとの記録（自分の台帳だけ）
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>;
SELECT run_id, corpus, ARRAY_SIZE(docs) AS n_pdfs, image_tag, status, message, started_at, ended_at
FROM <% db %>.<% schema_ops %>.RUNS ORDER BY started_at DESC LIMIT 10;
SELECT step, doc_id, status, attempt, n_errors, LEFT(error_text, 120) AS error_text, detail
FROM <% db %>.<% schema_ops %>.STEP_RUNS WHERE run_id = :run_id ORDER BY step, doc_id;

-- 2. AI の要求とキャッシュ（この run で新しく呼んだ数・解析失敗）
SELECT r.stage, COUNT(DISTINCT r.cache_key) AS n_requests,
       COUNT_IF(c.run_id = r.run_id) AS n_called_in_this_run, COUNT_IF(c.err IS NOT NULL) AS n_errors
FROM <% db %>.<% schema_work %>.AI_REQUESTS r
LEFT JOIN <% db %>.<% schema_work %>.AI_CACHE c ON c.cache_key = r.cache_key
WHERE r.run_id = :run_id GROUP BY r.stage ORDER BY r.stage;

-- 3. 生成物の一覧（ジョブはマウントしたステージに直接書くので、ディレクトリ表ではなく LIST で見る）
LIST @<% db %>.<% schema_output %>.RESULTS PATTERN = '.*/runs/.*/summary[.]json';

-- 4. 生成した関数のカード（関数名・種別・入力・根拠）を JSON で読む（ファイル形式 JSONL は setup が作る）
SELECT METADATA$FILENAME AS file, $1:function::STRING AS function, $1:kind::STRING AS kind,
       $1:title::STRING AS title, ARRAY_SIZE($1:inputs) AS n_inputs, $1:evidence_units AS evidence_units
FROM @<% db %>.<% schema_output %>.RESULTS (FILE_FORMAT => '<% db %>.<% schema_work %>.JSONL', PATTERN => '.*/runs/.*/cards[.]jsonl')
WHERE METADATA$FILENAME LIKE '%/runs/' || :run_id || '/%';

-- 5. 評価の要約と段ごとの損失（評価ロール）
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>;
SELECT eval_run_id, run_id, image_tag, n_rules_pass, n_rules, n_cases_pass, n_cases, n_errors,
       summary:discovery:lost_by_stage AS lost_by_stage, summary:discovery:recall AS discovery_recall
FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS WHERE run_id = :run_id ORDER BY created_at DESC;

-- 6. ルールごとの結果（対応した生成関数・不合格の段・ケースの種類ごとの合否）
SELECT pdf_id, function, pattern, passed, n_pass, n_cases, matched_gen, lost_stage, by_kind, selftest_passed
FROM <% eval_db %>.<% schema_results %>.RULE_RESULTS WHERE run_id = :run_id ORDER BY pdf_id, function;

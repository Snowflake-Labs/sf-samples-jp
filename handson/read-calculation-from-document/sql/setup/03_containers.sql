-- 03_containers.sql — ステージ・イメージリポジトリ・コンピュートプール・ジョブの台帳と、その権限。
-- 実行ロール：<% role_admin %>。冪等（IF NOT EXISTS。データを消さない）。
--   予測ロール：入力ステージ（PDF・手本）の READ、出力ステージの READ・WRITE、ジョブ仕様の READ、
--               イメージの READ、プールの USAGE、ジョブの作成。正解のステージには権限を与えない。
--   評価ロール：正解のステージの READ・WRITE、出力ステージの READ（生成物を採点する）。
USE ROLE <% role_admin %>;
USE WAREHOUSE <% warehouse %>;

-- ステージ（サーバー側の暗号化・ディレクトリ表つき）
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_raw %>.PDFS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = '予測の入力：照合済みの PDF・照合値（pdf_sha256.json）・手本だけ';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_output %>.RESULTS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = '生成物：pdoc・カード・計算仕様・Python・自己テスト・summary';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_app %>.SPECS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'ジョブ仕様のひな型';
CREATE STAGE IF NOT EXISTS <% eval_db %>.<% schema_gold %>.FILES
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = '正解（--eval のときだけ置く。評価ロールだけが読む）';

-- イメージとプール
CREATE IMAGE REPOSITORY IF NOT EXISTS <% db %>.<% schema_app %>.IMAGES;
CREATE COMPUTE POOL IF NOT EXISTS <% compute_pool %> MIN_NODES = 1 MAX_NODES = 1
  INSTANCE_FAMILY = <% compute_pool_family %> AUTO_RESUME = TRUE AUTO_SUSPEND_SECS = 300 INITIALLY_SUSPENDED = TRUE
  COMMENT = 'read-calculation-from-document';

-- ジョブの台帳
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.JOBS (
  run_id STRING, step STRING, job_name STRING, status STRING, started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ,
  message STRING, logs STRING);
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE <% db %> TO ROLE <% role_predict %>;

-- 権限
GRANT READ ON STAGE <% db %>.<% schema_raw %>.PDFS TO ROLE <% role_predict %>;
GRANT READ, WRITE ON STAGE <% db %>.<% schema_output %>.RESULTS TO ROLE <% role_predict %>;
GRANT READ ON STAGE <% db %>.<% schema_app %>.SPECS TO ROLE <% role_predict %>;
GRANT READ ON IMAGE REPOSITORY <% db %>.<% schema_app %>.IMAGES TO ROLE <% role_predict %>;
GRANT USAGE, MONITOR ON COMPUTE POOL <% compute_pool %> TO ROLE <% role_predict %>;
GRANT CREATE SERVICE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;

GRANT READ, WRITE ON STAGE <% eval_db %>.<% schema_gold %>.FILES TO ROLE <% role_eval %>;
GRANT READ ON STAGE <% db %>.<% schema_output %>.RESULTS TO ROLE <% role_eval %>;
GRANT USAGE, MONITOR ON COMPUTE POOL <% compute_pool %> TO ROLE <% role_eval %>;
GRANT USAGE ON SCHEMA <% db %>.<% schema_app %> TO ROLE <% role_eval %>;
GRANT READ ON STAGE <% db %>.<% schema_app %>.SPECS TO ROLE <% role_eval %>;
GRANT READ ON IMAGE REPOSITORY <% db %>.<% schema_app %>.IMAGES TO ROLE <% role_eval %>;
GRANT CREATE SERVICE ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;

-- 生成物の JSON Lines を SQL で読むためのファイル形式（sql/examples/queries.sql が使う）
CREATE FILE FORMAT IF NOT EXISTS <% db %>.<% schema_work %>.JSONL TYPE = JSON;
GRANT USAGE ON FILE FORMAT <% db %>.<% schema_work %>.JSONL TO ROLE <% role_predict %>;

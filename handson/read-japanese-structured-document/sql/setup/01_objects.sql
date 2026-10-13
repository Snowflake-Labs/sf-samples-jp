-- setup/01_objects.sql — ウェアハウス・DB・スキーマ・ステージ・台帳・キャッシュ・イメージリポジトリ・コンピュートプール
-- 実行ロール：<% role_admin %>。冪等（IF NOT EXISTS。データを消す OR REPLACE は使わない）。
-- 2 コーパスは同じオブジェクトを共有し、ステージのパスと表の corpus 列で分ける。
--   @RAW.DOCS     <corpus>/<doc_id>/doc.pdf
--   @RAW.WORK     runs/<run_id>/S30/<doc_id>/…・runs/<run_id>/crops/<rel_path>
--   @RAW.SHOTS    <corpus>/figure__*.json（図 few-shot の期待 JSON。setup が供出元の正解から生成）
--   @OUTPUT.RESULTS <run_id>/<corpus>/<doc_id>.json

USE ROLE <% role_admin %>;
USE SECONDARY ROLES NONE;

CREATE WAREHOUSE IF NOT EXISTS <% warehouse %>
  WAREHOUSE_SIZE = '<% warehouse_size %>' AUTO_SUSPEND = <% warehouse_auto_suspend %> AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'read-japanese-structured-document: SQL と AI 関数（大きくしても AI 関数は速くならない）';
USE WAREHOUSE <% warehouse %>;

-- ================================================================ 予測側 DB
CREATE DATABASE IF NOT EXISTS <% db %> COMMENT = 'read-japanese-structured-document: 読み取りと登録';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_raw %>    COMMENT = '入力 PDF・作業域（幾何・クロップ）・入力台帳';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_parsed %> COMMENT = 'AI 関数の応答キャッシュ';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_output %> COMMENT = '読み取り結果 JSON と登録表';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_ops %>    COMMENT = '台帳・プロシージャ・Task グラフ';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_app %>    COMMENT = 'イメージリポジトリ・ジョブ仕様';

-- SSE かつディレクトリ有効（クライアント側暗号化だと AI 関数がファイルを読めない。移植元 F21）
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_raw %>.DOCS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') COMMENT = '<corpus>/<doc_id>/doc.pdf';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_raw %>.WORK
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'runs/<run_id>/S30/<doc_id>/・runs/<run_id>/crops/<rel_path>';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_raw %>.SHOTS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') COMMENT = '<corpus>/figure__*.json';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_output %>.RESULTS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') COMMENT = '<run_id>/<corpus>/<doc_id>.json';
CREATE STAGE IF NOT EXISTS <% db %>.<% schema_app %>.SPECS
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') COMMENT = 'ジョブ仕様テンプレート';

-- 入力台帳（start が PUT のあとに書く）。md5 はステージのディレクトリ表と照合する
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_raw %>.FILES (
  corpus STRING, doc_id STRING, rel_path STRING, size_bytes NUMBER, md5 STRING, sha256 STRING,
  n_pages INT, page_w_pt FLOAT, page_h_pt FLOAT, dataset_version STRING,
  loaded_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());

-- AI 応答キャッシュ（S20）。cache_key = SHA2(corpus | doc_id | 入力の md5 | 関数 | オプション)
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_parsed %>.PARSE_RAW (
  cache_key STRING, corpus STRING, doc_id STRING, file_md5 STRING, fn STRING, model STRING, options VARIANT,
  options_hash STRING, prompt_version STRING, page_count INT, n_pages_returned INT, err STRING,
  query_id STRING, run_id STRING, created_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_parsed %>.PARSE_PAGES (
  cache_key STRING, doc_id STRING, page INT, content STRING, err STRING, page_count INT, query_id STRING);

-- AI 応答キャッシュ（S40）。1 図 1 行。キーは (image_md5, prompt_key)
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_parsed %>.FIGURE_RAW (
  image_md5 STRING, prompt_key STRING, rel_path STRING, stage_path STRING, corpus STRING, doc_id STRING,
  model STRING, prompt_version STRING, max_tokens INT, raw_out STRING, n_chars INT, err STRING, attempt INT,
  query_id STRING, run_id STRING, created_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());

-- ラン台帳・ステップ台帳。(run_id, step, doc_id) ごとに最新の状態を 1 行で持つ
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.RUNS (
  run_id STRING, corpus STRING, slice STRING, docs VARIANT, donors VARIANT, eval_excluded VARIANT,
  config VARIANT, image_tag STRING, dataset_version STRING, status STRING,
  started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ, message STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.STEP_RUNS (
  run_id STRING, step STRING, doc_id STRING, status STRING, started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ,
  attempt INT, image_tag STRING, query_id STRING, n_errors INT, error_text STRING, output_uri STRING,
  detail VARIANT);
-- ジョブの記録（S30・S50）。失敗時はサービスログの末尾を残す
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.JOBS (
  run_id STRING, step STRING, job_name STRING, status STRING, started_at TIMESTAMP_LTZ,
  ended_at TIMESTAMP_LTZ, message STRING, logs STRING);
-- S30 が検出した表・図領域（S40 の入力）
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.REGIONS (
  run_id STRING, corpus STRING, doc_id STRING, region_id STRING, kind STRING, page INT, rel_path STRING,
  stage_path STRING, bbox_pt STRING, width_px INT, height_px INT, n_cells_est INT, n_node_candidates INT,
  image_md5 STRING, prompt_key STRING, max_tokens INT);

-- 図 few-shot の規則本文と shot（コーパスごとに 1 行。setup が書き、S40 が読む）
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.FIGURE_PROMPT (
  corpus STRING, prompt_version STRING, model STRING, rules STRING,
  shot_a_doc STRING, shot_a_path STRING, shot_a_json STRING, shot_b_doc STRING, shot_b_path STRING, shot_b_json STRING,
  tokens_per_elem INT, min_max_tokens INT, retry_parse_error INT, loaded_at TIMESTAMP_LTZ);

-- 登録表（S55）。列は src/jpdocread/load/rows.py の columns() と同じ順
-- （tests/guard/test_sql_and_scripts.py が照合する）。冪等キー (run_id, corpus, doc_id)。配列を展開した表は seq を持つ
CREATE FILE FORMAT IF NOT EXISTS <% db %>.<% schema_output %>.JSON_DOC TYPE = JSON STRIP_OUTER_ARRAY = FALSE
  COMMENT = '出力 JSON（1 ファイル 1 オブジェクト）';
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.DOCUMENTS (
  run_id STRING, corpus STRING, doc_id STRING, schema_version STRING, title STRING, numbering_scheme STRING,
  n_pages INT, n_elements INT, n_errors INT, n_null_outputs INT, image_tag STRING, output_uri STRING,
  meta VARIANT, provenance VARIANT, extras VARIANT, registered_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.PAGES (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, page INT, page_class ARRAY, text STRING,
  text_with_furniture STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.OUTLINE (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, item_id STRING, depth INT, node_kind STRING, label STRING,
  title STRING, parent_id STRING, citation STRING, page INT, flags ARRAY);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.ELEMENTS (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, element_id STRING, kind STRING, node_kind STRING,
  label STRING, citation STRING, parent_id STRING, text STRING, pages ARRAY, refs_to ARRAY);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.TABLES (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, item_id STRING, pages ARRAY, source STRING,
  n_rows INT, n_cols INT, grid VARIANT);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.FIGURES (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, item_id STRING, pages ARRAY, bbox ARRAY, source STRING,
  nodes VARIANT, edges VARIANT, paths VARIANT, crop STRING, query_id STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.REFS (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, from_citation STRING, to_citation STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.PARTIES (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, alias STRING, name STRING, role STRING,
  declared_in STRING, page INT);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.DEFINED_TERMS (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, term STRING, defined_in STRING, source STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.TERM_USES (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, term STRING, in_citation STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_output %>.REPAIR_QUEUE (
  run_id STRING, corpus STRING, doc_id STRING, seq INT, kind STRING, locus STRING, evidence STRING,
  resolution STRING);

-- ================================================================ コンテナ
CREATE IMAGE REPOSITORY IF NOT EXISTS <% db %>.<% schema_app %>.IMAGES;
CREATE COMPUTE POOL IF NOT EXISTS <% compute_pool %>
  MIN_NODES = <% compute_pool_min_nodes %> MAX_NODES = <% compute_pool_max_nodes %>
  INSTANCE_FAMILY = <% compute_pool_family %>
  AUTO_RESUME = TRUE AUTO_SUSPEND_SECS = <% compute_pool_auto_suspend_secs %> INITIALLY_SUSPENDED = TRUE
  COMMENT = 'read-japanese-structured-document: S30・S50・S60 のジョブ';

-- ================================================================ 評価側 DB（予測側と DB レベルで分離）
CREATE DATABASE IF NOT EXISTS <% eval_db %> COMMENT = 'read-japanese-structured-document: 正解データと評価結果';
CREATE SCHEMA IF NOT EXISTS <% eval_db %>.<% schema_gold %>    COMMENT = '正解 JSON（--eval のときだけ置く）';
CREATE SCHEMA IF NOT EXISTS <% eval_db %>.<% schema_results %> COMMENT = '評価結果';
CREATE STAGE IF NOT EXISTS <% eval_db %>.<% schema_gold %>.FILES
  DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE') COMMENT = '<corpus>/<doc_id>/*.json・<corpus>/manifest.json';
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_gold %>.MANIFEST (
  corpus STRING, doc_id STRING, file STRING, sha256_manifest STRING, sha256_local STRING, checksum_ok BOOLEAN,
  loaded_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());
-- 評価の依頼（S60 のプロシージャが書き、評価ジョブが読む）と状態。予測側の台帳には評価値を書かない
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.EVAL_REQUESTS (
  run_id STRING, corpus STRING, docs VARIANT, eval_excluded VARIANT, image_tag STRING,
  requested_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.EVAL_STEPS (
  run_id STRING, status STRING, started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ, error_text STRING);
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.EVAL_RUNS (
  eval_run_id STRING, pred_run_id STRING, corpus STRING, image_tag STRING, payload VARIANT,
  created_at TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP());
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.DOC_METRICS (
  eval_run_id STRING, pred_run_id STRING, corpus STRING, doc_id STRING, style_id STRING, genre STRING, payload VARIANT);
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.PAGE_METRICS (
  eval_run_id STRING, pred_run_id STRING, corpus STRING, doc_id STRING, page INT, payload VARIANT);
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.ELEMENT_ERRORS (
  eval_run_id STRING, pred_run_id STRING, corpus STRING, doc_id STRING, payload VARIANT);

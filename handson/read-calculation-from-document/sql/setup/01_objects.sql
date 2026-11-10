-- 01_objects.sql — ウェアハウス・DB・スキーマ・台帳の表。
-- 実行ロール：<% role_admin %>。冪等（IF NOT EXISTS。データを消さない）。
-- ステージ・イメージリポジトリ・コンピュートプールは 03_containers.sql（SPCS で動かすときに作る）。
USE ROLE <% role_admin %>;

CREATE WAREHOUSE IF NOT EXISTS <% warehouse %> WAREHOUSE_SIZE = <% warehouse_size %> AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE COMMENT = 'read-calculation-from-document';
USE WAREHOUSE <% warehouse %>;

-- 予測側
CREATE DATABASE IF NOT EXISTS <% db %> COMMENT = 'read-calculation-from-document: 予測側';
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_raw %>;
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_work %>;
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_output %>;
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_ops %>;
CREATE SCHEMA IF NOT EXISTS <% db %>.<% schema_app %>;

-- 評価側（予測ロールには権限を与えない）
CREATE DATABASE IF NOT EXISTS <% eval_db %> COMMENT = 'read-calculation-from-document: 評価側（正解と評価結果）';
CREATE SCHEMA IF NOT EXISTS <% eval_db %>.<% schema_gold %>;
CREATE SCHEMA IF NOT EXISTS <% eval_db %>.<% schema_results %>;

-- 評価の台帳（評価側。予測ロールには権限を与えない）
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.EVAL_RUNS (
  eval_run_id STRING, run_id STRING, corpus STRING, dataset_revision STRING, image_tag STRING,
  n_pdfs INT, n_rules INT, n_rules_pass INT, n_cases INT, n_cases_pass INT, n_errors INT,
  summary VARIANT, created_at TIMESTAMP_LTZ);
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.RULE_RESULTS (
  eval_run_id STRING, run_id STRING, pdf_id STRING, function STRING, rule STRING, pattern STRING,
  passed BOOLEAN, n_cases INT, n_pass INT, by_kind VARIANT, modalities ARRAY, difficulty VARIANT,
  figure_only BOOLEAN, placement STRING, selftest_passed BOOLEAN, matched_gen STRING,
  args_complete BOOLEAN, extra_gen_args INT, lost_stage STRING,
  passed_neutral_fill BOOLEAN, passed_without_omitted BOOLEAN);
CREATE TABLE IF NOT EXISTS <% eval_db %>.<% schema_results %>.EVAL_JOBS (
  eval_run_id STRING, run_id STRING, job_name STRING, status STRING, started_at TIMESTAMP_LTZ,
  ended_at TIMESTAMP_LTZ, message STRING, logs STRING);

-- 台帳
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.RUNS (
  run_id STRING, corpus STRING, slice STRING, docs ARRAY, config VARIANT, image_tag STRING,
  started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ, status STRING, message STRING);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_ops %>.STEP_RUNS (
  run_id STRING, step STRING, doc_id STRING, status STRING, started_at TIMESTAMP_LTZ, ended_at TIMESTAMP_LTZ,
  attempt INT DEFAULT 0, image_tag STRING, n_errors INT, error_text STRING, output_uri STRING, detail VARIANT);

-- AI の呼び出し：要求は予測が書き、<% schema_ops %>.AI_CALL がキャッシュに無い行だけを処理する
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_work %>.AI_REQUESTS (
  run_id STRING, batch_id STRING, cache_key STRING, stage STRING, doc_id STRING, unit STRING,
  model STRING, max_tokens INT, prompt_version STRING, expect STRING, prompt STRING, created_at TIMESTAMP_LTZ);
CREATE TABLE IF NOT EXISTS <% db %>.<% schema_work %>.AI_CACHE (
  cache_key STRING, stage STRING, doc_id STRING, unit STRING, model STRING, max_tokens INT, prompt_version STRING,
  raw_out STRING, n_chars INT, err STRING, query_id STRING, run_id STRING, called_at TIMESTAMP_LTZ);

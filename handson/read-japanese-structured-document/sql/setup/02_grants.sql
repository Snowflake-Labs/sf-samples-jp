-- setup/02_grants.sql — ロールごとの権限
-- 実行ロール：<% role_admin %>（全オブジェクトのオーナー）。冪等。
--
--   PREDICT：<% db %> の読み書きと実行だけ。<% eval_db %> には一切の権限を与えない。
--   EVAL   ：<% eval_db %> の全権 ＋ 読み取り結果ステージ（OUTPUT.RESULTS）の READ だけ。
--            予測側の他のスキーマ（PARSED・RAW の表）は読めない（sql/verify/roles.sql で確かめる）。
--
-- FUTURE GRANTS は使わない。DB 単位・スキーマ単位とも MANAGE GRANTS（アカウント権限）が要り、本プロジェクトの
-- ロールにアカウント権限を足したくないため。表は setup が先に作り、本ファイルの ON ALL TABLES で
-- 付与する。setup を再実行すれば、後から足した表にも付与される。

USE ROLE <% role_admin %>;
USE SECONDARY ROLES NONE;

-- ---------------------------------------------------------------- 共通
GRANT USAGE, OPERATE ON WAREHOUSE <% warehouse %> TO ROLE <% role_predict %>;
GRANT USAGE, OPERATE ON WAREHOUSE <% warehouse %> TO ROLE <% role_eval %>;
GRANT USAGE, MONITOR ON COMPUTE POOL <% compute_pool %> TO ROLE <% role_predict %>;
GRANT USAGE, MONITOR ON COMPUTE POOL <% compute_pool %> TO ROLE <% role_eval %>;

-- ---------------------------------------------------------------- PREDICT（<% db %> のみ）
GRANT USAGE ON DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT USAGE ON ALL SCHEMAS IN DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT READ, WRITE ON STAGE <% db %>.<% schema_raw %>.DOCS TO ROLE <% role_predict %>;
GRANT READ, WRITE ON STAGE <% db %>.<% schema_raw %>.WORK TO ROLE <% role_predict %>;
GRANT READ ON STAGE <% db %>.<% schema_raw %>.SHOTS TO ROLE <% role_predict %>;
GRANT READ, WRITE ON STAGE <% db %>.<% schema_output %>.RESULTS TO ROLE <% role_predict %>;
GRANT READ ON STAGE <% db %>.<% schema_app %>.SPECS TO ROLE <% role_predict %>;
GRANT READ ON IMAGE REPOSITORY <% db %>.<% schema_app %>.IMAGES TO ROLE <% role_predict %>;
GRANT USAGE ON FILE FORMAT <% db %>.<% schema_output %>.JSON_DOC TO ROLE <% role_predict %>;
GRANT CREATE SERVICE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;
GRANT CREATE TASK ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;
GRANT CREATE PROCEDURE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;
GRANT CREATE TABLE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;  -- プロシージャの一時表
GRANT CREATE VIEW, CREATE FUNCTION ON SCHEMA <% db %>.<% schema_output %> TO ROLE <% role_predict %>;  -- 照会用ビューと照合キー（sql/views/output_views.sql）

-- ---------------------------------------------------------------- EVAL（<% eval_db %> ＋ 読み取り結果の READ）
GRANT USAGE ON DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT USAGE ON ALL SCHEMAS IN DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT READ, WRITE ON STAGE <% eval_db %>.<% schema_gold %>.FILES TO ROLE <% role_eval %>;
GRANT CREATE SERVICE ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
GRANT CREATE PROCEDURE ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
GRANT CREATE VIEW ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
GRANT CREATE TABLE ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
-- 読み取り結果の読み取り（採点の入力）。予測側の他のスキーマ・表には触れさせない
GRANT USAGE ON DATABASE <% db %> TO ROLE <% role_eval %>;
GRANT USAGE ON SCHEMA <% db %>.<% schema_output %> TO ROLE <% role_eval %>;
GRANT USAGE ON SCHEMA <% db %>.<% schema_app %> TO ROLE <% role_eval %>;
GRANT READ ON STAGE <% db %>.<% schema_output %>.RESULTS TO ROLE <% role_eval %>;
GRANT READ ON STAGE <% db %>.<% schema_app %>.SPECS TO ROLE <% role_eval %>;
GRANT READ ON IMAGE REPOSITORY <% db %>.<% schema_app %>.IMAGES TO ROLE <% role_eval %>;
-- S60 の起動プロシージャ（オーナーは評価ロール）を、予測ロールが呼べる OPS に置く（移植元と同じ）。
-- 評価ロールが OPS で読めるのは RUNS（対象文書と供出元）だけ。台帳・キャッシュ・登録表には権限を与えない
GRANT USAGE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_eval %>;
GRANT CREATE PROCEDURE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_eval %>;
GRANT SELECT ON TABLE <% db %>.<% schema_ops %>.RUNS TO ROLE <% role_eval %>;

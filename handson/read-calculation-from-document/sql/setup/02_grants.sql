-- 02_grants.sql — ロールごとの権限。実行ロール：<% role_admin %>。冪等。
--   予測ロール：予測側の DB の読み書きと実行だけ。評価側の DB には一切の権限を与えない。
--   評価ロール：評価側の DB の全権と、予測の台帳（RUNS）の SELECT。
-- ステージ・イメージリポジトリ・コンピュートプールの権限は 03_containers.sql。
-- 将来の表への付与（ON FUTURE）は MANAGE GRANTS（アカウント全体の付与の権限）が要るので使わない。
-- 表はすべて setup で作り、表を足したら setup を流し直す（ON ALL TABLES で付与される。冪等）。
USE ROLE <% role_admin %>;

GRANT USAGE, OPERATE ON WAREHOUSE <% warehouse %> TO ROLE <% role_predict %>;
GRANT USAGE, OPERATE ON WAREHOUSE <% warehouse %> TO ROLE <% role_eval %>;

GRANT USAGE ON DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT USAGE ON ALL SCHEMAS IN DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE <% db %> TO ROLE <% role_predict %>;
GRANT CREATE PROCEDURE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;
GRANT CREATE TASK ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_predict %>;
GRANT CREATE TABLE ON SCHEMA <% db %>.<% schema_work %> TO ROLE <% role_predict %>;

GRANT USAGE ON DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT USAGE ON ALL SCHEMAS IN DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN DATABASE <% eval_db %> TO ROLE <% role_eval %>;
GRANT CREATE PROCEDURE ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
GRANT CREATE VIEW ON SCHEMA <% eval_db %>.<% schema_results %> TO ROLE <% role_eval %>;
GRANT USAGE ON DATABASE <% db %> TO ROLE <% role_eval %>;
GRANT USAGE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_eval %>;
GRANT USAGE ON SCHEMA <% db %>.<% schema_output %> TO ROLE <% role_eval %>;
GRANT SELECT ON TABLE <% db %>.<% schema_ops %>.RUNS TO ROLE <% role_eval %>;
-- 評価の起動（S20）：評価ロールが予測側の OPS に自分の所有のプロシージャを置き、予測ロールに USAGE を渡す
-- （予測ロールは評価 DB を見ずに、自分の run の採点を起動できるだけ。結果は読めない）
GRANT CREATE PROCEDURE ON SCHEMA <% db %>.<% schema_ops %> TO ROLE <% role_eval %>;

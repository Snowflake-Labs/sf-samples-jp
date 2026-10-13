-- verify/roles.sql — ロール分離の検証
-- scripts/verify_roles.sh が 1 ケースずつ実行し、期待（ok / fail）と照合する。1 件でも違えば非 0 で終わる。
--
-- **USE SECONDARY ROLES NONE を必ず併用する。** DEFAULT_SECONDARY_ROLES = ('ALL') のアカウントでは、
-- USE ROLE だけでは付与済みの全ロールの権限が併用され、偽の合格になる。
-- 「fail を期待するケース」には、同じ対象を別のロールで読めることを確かめる「ok のケース」を必ず対にする
-- （対象が無いせいで fail になる偽の合格を防ぐ）。
--
-- 形式：「-- expect: ok|fail」の次の 1 行が 1 ケース。

-- 予測ロールは評価 DB の表もステージも読めない（対照：評価ロールは読める）
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% eval_db %>.<% schema_gold %>.FILES;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% eval_db %>.<% schema_gold %>.FILES;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_gold %>.MANIFEST;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_gold %>.MANIFEST;

-- 評価ロールは読み取り結果のステージだけを読め、予測側のキャッシュ・台帳・入力は読めない（対照：予測ロールは読める）
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_output %>.RESULTS;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_parsed %>.PARSE_RAW;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_parsed %>.PARSE_RAW;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_raw %>.FILES;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_raw %>.FILES;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.DOCS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.DOCS;

-- 評価ロールは作業域（クロップ）と図 few-shot（正解由来）を読めず、読み取り結果に書けない
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.WORK;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.WORK;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.SHOTS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.SHOTS;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_output %>.RESULTS/__role_check_none__;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_output %>.RESULTS/__role_check_none__;

-- 評価ロールは OPS では RUNS だけを読め、台帳と登録表は読めない（S60 の起動に要る最小限）
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_ops %>.RUNS;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_ops %>.STEP_RUNS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_ops %>.STEP_RUNS;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_output %>.ELEMENTS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% db %>.<% schema_output %>.ELEMENTS;
-- 予測ロールは評価の依頼・状態の表にも触れない
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.EVAL_REQUESTS;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.EVAL_REQUESTS;

-- オーナーは両方を読める
-- expect: ok
USE ROLE <% role_admin %>; USE SECONDARY ROLES NONE; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.EVAL_RUNS;

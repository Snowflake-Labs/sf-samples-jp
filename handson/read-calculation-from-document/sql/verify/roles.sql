-- ロール分離の検証。各ケースは 1 行で、直前の `-- expect:` と照合する（ok：成功する／fail：権限で失敗する）。
-- 書き込みの権限は REMOVE（対象が無ければ 0 件で成功する。WRITE が無ければ権限で失敗する）で確かめる。
-- 各ケースの先頭で USE SECONDARY ROLES NONE を実行する（アカウントの既定の副ロールで偽の合格にしない）。
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SHOW SCHEMAS IN DATABASE <% eval_db %>;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% eval_db %>.<% schema_gold %>.FILES;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_raw %>.PDFS/__no_such_file__;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% db %>.<% schema_ops %>.RUNS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.PDFS;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_output %>.RESULTS;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% eval_db %>.<% schema_gold %>.FILES;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_output %>.RESULTS;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% db %>.<% schema_work %>.AI_CACHE;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; LIST @<% db %>.<% schema_raw %>.PDFS;
-- expect: ok
USE ROLE <% role_admin %>; USE SECONDARY ROLES NONE; LIST @<% eval_db %>.<% schema_gold %>.FILES;
-- expect: ok
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_output %>.RESULTS/__no_such_file__;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_output %>.RESULTS/__no_such_file__;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; REMOVE @<% db %>.<% schema_app %>.SPECS/__no_such_file__;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.NO_SUCH_TABLE;
-- expect: fail
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% db %>.<% schema_ops %>.JOBS;
-- expect: fail
USE ROLE <% role_predict %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.RULE_RESULTS;
-- expect: ok
USE ROLE <% role_eval %>; USE SECONDARY ROLES NONE; USE WAREHOUSE <% warehouse %>; SELECT COUNT(*) FROM <% eval_db %>.<% schema_results %>.RULE_RESULTS;

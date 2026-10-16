-- setup/00_roles.sql — ロールとアカウント権限
-- 実行ロール：ACCOUNTADMIN（ロール作成とアカウント権限の付与に必要）。冪等（IF NOT EXISTS・GRANT は再実行しても同じ）。
-- 変数（CLI の -D で渡す。scripts/lib.sh が jpdocread names から作る）：role_admin role_predict role_eval

USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS <% role_admin %>   COMMENT = 'read-japanese-structured-document: オブジェクトのオーナー（setup/teardown）';
CREATE ROLE IF NOT EXISTS <% role_predict %> COMMENT = 'read-japanese-structured-document: 読み取りと登録（評価 DB の権限なし）';
CREATE ROLE IF NOT EXISTS <% role_eval %>    COMMENT = 'read-japanese-structured-document: 評価（正解と評価結果）';

-- 孤立ロールを作らない：ADMIN を SYSADMIN 配下に、PREDICT・EVAL を ADMIN 配下に置く
GRANT ROLE <% role_admin %>   TO ROLE SYSADMIN;
GRANT ROLE <% role_predict %> TO ROLE <% role_admin %>;
GRANT ROLE <% role_eval %>    TO ROLE <% role_admin %>;

-- setup を実行しているユーザーに ADMIN を付与する（ユーザー名をリポジトリに書かない）
SET deploy_user = CURRENT_USER();
GRANT ROLE <% role_admin %> TO USER IDENTIFIER($deploy_user);

-- アカウント権限（ACCOUNTADMIN でしか付与できない）
GRANT CREATE DATABASE     ON ACCOUNT TO ROLE <% role_admin %>;
GRANT CREATE WAREHOUSE    ON ACCOUNT TO ROLE <% role_admin %>;
GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE <% role_admin %>;
GRANT EXECUTE TASK        ON ACCOUNT TO ROLE <% role_admin %>;
GRANT EXECUTE TASK        ON ACCOUNT TO ROLE <% role_predict %>;
-- AI 関数（AI_PARSE_DOCUMENT・AI_COMPLETE）は予測ロールだけが使う
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <% role_predict %>;

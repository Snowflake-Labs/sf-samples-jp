-- 00_roles.sql — ロールとアカウントの権限。
-- 実行ロール：ACCOUNTADMIN（ロールの作成とアカウントの権限の付与に要る）。冪等。アカウントのパラメータには触れない。
-- <% user %> はセットアップを実行するユーザー（実行時に CURRENT_USER() から取る。ファイルに書かない）。
USE ROLE ACCOUNTADMIN;

CREATE ROLE IF NOT EXISTS <% role_admin %>   COMMENT = 'read-calculation-from-document: オブジェクトのオーナー（setup・teardown）';
CREATE ROLE IF NOT EXISTS <% role_predict %> COMMENT = 'read-calculation-from-document: 予測（評価 DB の権限なし）';
CREATE ROLE IF NOT EXISTS <% role_eval %>    COMMENT = 'read-calculation-from-document: 採点（正解と評価結果）';

GRANT ROLE <% role_admin %>   TO ROLE SYSADMIN;
GRANT ROLE <% role_predict %> TO ROLE <% role_admin %>;
GRANT ROLE <% role_eval %>    TO ROLE <% role_admin %>;
GRANT ROLE <% role_admin %>   TO USER <% user %>;
GRANT ROLE <% role_predict %> TO USER <% user %>;
GRANT ROLE <% role_eval %>    TO USER <% user %>;

GRANT CREATE DATABASE     ON ACCOUNT TO ROLE <% role_admin %>;
GRANT CREATE WAREHOUSE    ON ACCOUNT TO ROLE <% role_admin %>;
GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE <% role_admin %>;
GRANT EXECUTE TASK        ON ACCOUNT TO ROLE <% role_admin %>;
GRANT EXECUTE TASK        ON ACCOUNT TO ROLE <% role_predict %>;
-- AI_COMPLETE を予測ロールだけに許す（評価ロールは AI を呼ばない）
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <% role_predict %>;

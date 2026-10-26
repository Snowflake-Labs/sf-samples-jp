-- 00_common/sql/01_account.sql
-- 共通基盤: ロール・ウェアハウス・データベース・スキーマ（APP / AGENTS / INTERNAL）を作成する。再実行可能。
-- Creates workshop-owned account objects: role, warehouse, database, schemas.
-- Idempotent. Requires ACCOUNTADMIN (or an equivalent role).

USE ROLE ACCOUNTADMIN;

-- Cortex Agents may need cross-region inference when a model is not hosted locally.
-- This is an account-level setting; the hands-on only enables it when it is DISABLED.
-- Check first:  SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
-- If DISABLED, run (requires ACCOUNTADMIN):
--   ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

CREATE ROLE IF NOT EXISTS <% role %>
    COMMENT = 'multi-agent-patterns role';
-- Grant the role to whoever runs this file (no user-name placeholder needed).
SET handson_user = '"' || CURRENT_USER() || '"';
GRANT ROLE <% role %> TO USER IDENTIFIER($handson_user);
GRANT ROLE <% role %> TO ROLE ACCOUNTADMIN;

CREATE WAREHOUSE IF NOT EXISTS <% wh %>
    WAREHOUSE_SIZE = '<% wh_size %>'
    AUTO_SUSPEND = <% wh_suspend %>
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'multi-agent-patterns warehouse';

CREATE DATABASE IF NOT EXISTS <% db %>
    COMMENT = 'multi-agent-patterns database';
CREATE SCHEMA IF NOT EXISTS <% db %>.APP      COMMENT = 'Task management data';
CREATE SCHEMA IF NOT EXISTS <% db %>.AGENTS   COMMENT = 'Cortex Agents, semantic view, tools, Streamlit';
CREATE SCHEMA IF NOT EXISTS <% db %>.INTERNAL COMMENT = 'Proposals, verification, audit, run trace';

USE WAREHOUSE <% wh %>;

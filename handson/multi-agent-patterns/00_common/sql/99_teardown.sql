-- 00_common/sql/99_teardown.sql
-- 共通基盤とパターン 01-04 のオブジェクト（DB 内のすべて）、ウェアハウス、ロールを削除する。
-- Removes ONLY the objects created by multi-agent-patterns. Idempotent.
-- It does not change account parameters (for example CORTEX_ENABLED_CROSS_REGION).

USE ROLE ACCOUNTADMIN;

DROP DATABASE IF EXISTS <% db %>;   -- tables, views, semantic view, procedures, agents, stage, optional Streamlit
DROP WAREHOUSE IF EXISTS <% wh %>;
DROP ROLE IF EXISTS <% role %>;

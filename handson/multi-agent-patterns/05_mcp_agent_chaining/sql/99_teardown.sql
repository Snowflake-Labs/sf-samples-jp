-- 05_mcp_agent_chaining/sql/99_teardown.sql
-- パターン 05 のデータベースだけを削除する（共通ウェアハウスは 00_common/teardown.sh で削除）。
USE ROLE ACCOUNTADMIN;
DROP DATABASE IF EXISTS <% mcp_db %>;

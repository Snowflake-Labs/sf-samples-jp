-- 05_mcp_agent_chaining/sql/99_teardown.sql
-- Delete only the pattern 05 database; 00_common/teardown.sh deletes the shared warehouse.
USE ROLE ACCOUNTADMIN;
DROP DATABASE IF EXISTS <% mcp_db %>;

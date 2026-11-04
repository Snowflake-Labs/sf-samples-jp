-- 05_mcp_agent_chaining/sql/01_namespace.sql
-- Dedicated namespace for pattern 05. Create the shared warehouse if it does not exist.
USE ROLE ACCOUNTADMIN;
CREATE WAREHOUSE IF NOT EXISTS <% wh %> WAREHOUSE_SIZE = '<% wh_size %>' AUTO_SUSPEND = <% wh_suspend %> AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE COMMENT = 'multi-agent-patterns';
CREATE DATABASE IF NOT EXISTS <% mcp_db %> COMMENT = 'multi-agent-patterns: 05 MCP agent chaining';
CREATE SCHEMA IF NOT EXISTS <% mcp_db %>.LAB;

-- 06_skill_composition/sql/01_namespace.sql
-- Dedicated namespace for pattern 06. Create the shared warehouse if it does not exist.
USE ROLE ACCOUNTADMIN;
CREATE WAREHOUSE IF NOT EXISTS <% wh %> WAREHOUSE_SIZE = '<% wh_size %>' AUTO_SUSPEND = <% wh_suspend %> AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE COMMENT = 'multi-agent-patterns';
CREATE DATABASE IF NOT EXISTS <% skill_db %> COMMENT = 'multi-agent-patterns: 06 skill composition';
CREATE SCHEMA IF NOT EXISTS <% skill_db %>.LAB;
CREATE STAGE IF NOT EXISTS <% skill_db %>.LAB.SKILL_STAGE DIRECTORY = (ENABLE = TRUE)
  COMMENT = 'SKILL.md folders for the pattern 06 agents';

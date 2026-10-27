-- 02_orchestrator_worker/sql/99_teardown.sql
-- Delete only this pattern's agents and procedure; keep the common foundation.

USE ROLE ACCOUNTADMIN;

DROP AGENT IF EXISTS <% db %>.AGENTS.TMS_DECOMPOSER_AGENT;
DROP AGENT IF EXISTS <% db %>.AGENTS.TMS_DEDUPE_AGENT;
DROP AGENT IF EXISTS <% db %>.AGENTS.TMS_CRITERIA_AGENT;
DROP PROCEDURE IF EXISTS <% db %>.APP.RUN_MEETING_NOTE(STRING);

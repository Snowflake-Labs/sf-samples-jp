-- 02_orchestrator_worker/sql/30_grants.sql
-- Grant the execution role access to this pattern's agents and procedure.

USE ROLE ACCOUNTADMIN;

GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_DECOMPOSER_AGENT TO ROLE <% role %>;
GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_DEDUPE_AGENT TO ROLE <% role %>;
GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_CRITERIA_AGENT TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.APP.RUN_MEETING_NOTE(STRING) TO ROLE <% role %>;

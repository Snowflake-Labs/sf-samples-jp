-- 01_router_handoff/sql/30_grants.sql
-- Grant the execution role access to this pattern's agents and procedure.

USE ROLE ACCOUNTADMIN;

GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_ROUTER_AGENT TO ROLE <% role %>;
GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_INTAKE_AGENT TO ROLE <% role %>;
GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_STATUS_AGENT TO ROLE <% role %>;
GRANT USAGE ON AGENT <% db %>.AGENTS.TMS_CHANGE_AGENT TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.APP.RUN_INBOX_REQUEST(STRING, STRING) TO ROLE <% role %>;

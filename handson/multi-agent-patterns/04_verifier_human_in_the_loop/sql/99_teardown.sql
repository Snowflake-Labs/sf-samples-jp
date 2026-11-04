-- 04_verifier_human_in_the_loop/sql/99_teardown.sql
-- Delete only this pattern's agent and procedures; keep the common foundation.

USE ROLE ACCOUNTADMIN;

DROP AGENT IF EXISTS <% db %>.AGENTS.TMS_VERIFIER_AGENT;
DROP PROCEDURE IF EXISTS <% db %>.APP.RUN_VERIFICATION(STRING);
DROP PROCEDURE IF EXISTS <% db %>.APP.DECIDE_PROPOSAL(STRING, STRING);
DROP PROCEDURE IF EXISTS <% db %>.APP.APPLY_PROPOSAL(STRING);

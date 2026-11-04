-- 00_common/sql/08_grants.sql
-- Least-privilege grants for the common foundation. The execution role can read tasks but cannot modify APP.TASKS directly.
-- Writes follow one path only: verification -> human approval -> INTERNAL.APPLY_APPROVED_ACTION -> audit.
-- Each pattern grants access to its agents and procedures in sql/30_grants.sql.

USE ROLE ACCOUNTADMIN;

GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE <% role %>;
GRANT USAGE ON WAREHOUSE <% wh %> TO ROLE <% role %>;
GRANT USAGE ON DATABASE <% db %> TO ROLE <% role %>;
GRANT USAGE ON SCHEMA <% db %>.APP TO ROLE <% role %>;
GRANT USAGE ON SCHEMA <% db %>.AGENTS TO ROLE <% role %>;
GRANT USAGE ON SCHEMA <% db %>.INTERNAL TO ROLE <% role %>;

-- Read access to business data and the semantic view.
GRANT SELECT ON ALL TABLES IN SCHEMA <% db %>.APP TO ROLE <% role %>;
GRANT SELECT ON SEMANTIC VIEW <% db %>.AGENTS.TMS_SEMANTIC_VIEW TO ROLE <% role %>;

-- Control plane: read everything, but append only proposals and trace events.
GRANT SELECT ON ALL TABLES IN SCHEMA <% db %>.INTERNAL TO ROLE <% role %>;
GRANT INSERT ON TABLE <% db %>.INTERNAL.PROPOSED_ACTIONS TO ROLE <% role %>;
GRANT INSERT ON TABLE <% db %>.INTERNAL.RUN_EVENTS TO ROLE <% role %>;

-- Read-only tools and owner-rights write procedures for controllers.
GRANT USAGE ON PROCEDURE <% db %>.AGENTS.GET_TASK(STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.AGENTS.SEARCH_SIMILAR_TASKS(STRING, STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.AGENTS.GET_PROJECT_POLICY(STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.AGENTS.VALIDATE_PROPOSED_ACTION(STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.INTERNAL.RECORD_VERIFICATION(STRING, STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.INTERNAL.DECIDE_ACTION(STRING, STRING, STRING) TO ROLE <% role %>;
GRANT USAGE ON PROCEDURE <% db %>.INTERNAL.APPLY_APPROVED_ACTION(STRING, STRING) TO ROLE <% role %>;

-- Controller ZIP and inspection views.
GRANT READ ON STAGE <% db %>.AGENTS.APP_STAGE TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_REVIEW_QUEUE TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_RUN_TRACE TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_TASK_BOARD TO ROLE <% role %>;

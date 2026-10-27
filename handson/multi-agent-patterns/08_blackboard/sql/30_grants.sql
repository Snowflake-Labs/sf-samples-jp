-- 08_blackboard/sql/30_grants.sql
-- Grant only the post entry point and inspection views; deny direct board writes and task operations.

USE ROLE ACCOUNTADMIN;

GRANT USAGE ON PROCEDURE <% db %>.APP.POST_MEETING_NOTE(STRING) TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_BOARD_TIMELINE TO ROLE <% role %>;
GRANT SELECT ON VIEW <% db %>.APP.V_BOARD_INBOX TO ROLE <% role %>;

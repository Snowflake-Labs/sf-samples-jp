-- 08_blackboard/sql/25_tasks.sql
-- Per-subscriber triggered tasks with no schedule; they run only when stream data arrives.
-- No data means no execution. Tasks run as their owner role, which is the role that executes this file.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE TASK <% db %>.INTERNAL.BOARD_T_DECOMPOSE
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 08 subscriber: decompose (consumes NOTE)'
    WHEN SYSTEM$STREAM_HAS_DATA('<% db %>.INTERNAL.BOARD_S_DECOMPOSE')
AS
    CALL <% db %>.INTERNAL.BOARD_REACT('decompose');

CREATE OR REPLACE TASK <% db %>.INTERNAL.BOARD_T_DEDUPE
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 08 subscriber: dedupe (consumes CANDIDATES)'
    WHEN SYSTEM$STREAM_HAS_DATA('<% db %>.INTERNAL.BOARD_S_DEDUPE')
AS
    CALL <% db %>.INTERNAL.BOARD_REACT('dedupe');

CREATE OR REPLACE TASK <% db %>.INTERNAL.BOARD_T_CRITERIA
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 08 subscriber: criteria (consumes CANDIDATES)'
    WHEN SYSTEM$STREAM_HAS_DATA('<% db %>.INTERNAL.BOARD_S_CRITERIA')
AS
    CALL <% db %>.INTERNAL.BOARD_REACT('criteria');

CREATE OR REPLACE TASK <% db %>.INTERNAL.BOARD_T_ASSEMBLE
    WAREHOUSE = <% wh %>
    COMMENT = 'Pattern 08 subscriber: assemble (consumes DEDUPE, CRITERIA)'
    WHEN SYSTEM$STREAM_HAS_DATA('<% db %>.INTERNAL.BOARD_S_ASSEMBLE')
AS
    CALL <% db %>.INTERNAL.BOARD_REACT('assemble');

ALTER TASK <% db %>.INTERNAL.BOARD_T_DECOMPOSE RESUME;
ALTER TASK <% db %>.INTERNAL.BOARD_T_DEDUPE RESUME;
ALTER TASK <% db %>.INTERNAL.BOARD_T_CRITERIA RESUME;
ALTER TASK <% db %>.INTERNAL.BOARD_T_ASSEMBLE RESUME;

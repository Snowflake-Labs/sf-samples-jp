-- 08_blackboard/sql/22_react.sql
-- Owner-rights subscriber processing. controller/src/board.py SUBSCRIBERS fixes each subscriber's writable kinds.
-- Record exceptions as ERROR in the inbox instead of failing the task and repeatedly processing the same data.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.BOARD_REACT(SUBSCRIBER STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Pattern 08: one subscriber reacts to new board items and writes its own kind back'
EXECUTE AS OWNER
AS
$$
from src import board
from src.config import Config


def run(session, subscriber):
    try:
        return board.react(session, Config("<% db %>"), (subscriber or "").strip().lower())
    except Exception as exc:  # never fail the task
        return {"ok": False, "error": str(exc)[:500]}
$$;

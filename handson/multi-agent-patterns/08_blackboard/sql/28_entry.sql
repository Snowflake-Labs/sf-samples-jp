-- 08_blackboard/sql/28_entry.sql
-- Owner-rights entry point: post a meeting note as NOTE; subscribers react asynchronously afterward.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE OR REPLACE PROCEDURE <% db %>.APP.POST_MEETING_NOTE(NOTE_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Pattern 08: post a meeting note to the blackboard (asynchronous); returns the run id'
EXECUTE AS OWNER
AS
$$
from src import audit, board
from src.config import Config

DB = "<% db %>"


def run(session, note_id):
    note_id = (note_id or "").strip().upper()
    rows = session.sql(f"SELECT NOTE_ID, PROJECT_ID FROM {DB}.APP.MEETING_NOTES WHERE NOTE_ID = ?", params=[note_id]).collect()
    if not rows:
        return {"ok": False, "error": f"meeting note {note_id!r} not found"}
    run_id = audit.new_id("BRD")
    item_id = board.write_item(session, Config(DB), board.POSTER, "NOTE", run_id, None,
                               {"note_id": note_id, "project_id": rows[0]["PROJECT_ID"]})
    return {"ok": True, "run_id": run_id, "item_id": item_id,
            "message": "posted; SELECT * FROM APP.V_BOARD_TIMELINE WHERE RUN_ID = '" + run_id + "' ORDER BY CREATED_AT"}
$$;

-- 08_blackboard/sql/22_react.sql
-- 購読者の処理（所有者権限）。購読者 → 書ける種類の対応表は controller/src/board.py の SUBSCRIBERS で固定。
-- 例外は外に出さず受信箱に ERROR を記録する（タスクが失敗して同じデータで再実行され続けるのを防ぐ）。

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

-- 04_verifier_human_in_the_loop/sql/20_procedures.sql
-- Controller procedures for verification, human approval or discard, and application.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

-------------------------------------------------------------------------------
-- Verifier: deterministic checks -> verifier agent -> recorded verdict.
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.RUN_VERIFICATION(ACTION_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Verifier: verify one proposed action (deterministic checks, then verifier agent)'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, action_id):
    return controller.verify_action(session, Config("<% db %>"), action_id)
$$;

-------------------------------------------------------------------------------
-- Human decision and apply. Explicit calls only; approver = CURRENT_USER().
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.APP.DECIDE_PROPOSAL(ACTION_ID STRING, DECISION STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Human approval: APPROVE a VERIFIED action or DISCARD it'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, action_id, decision):
    return controller.decide(session, Config("<% db %>"), action_id, decision, controller.current_user(session))
$$;

CREATE OR REPLACE PROCEDURE <% db %>.APP.APPLY_PROPOSAL(ACTION_ID STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pandas')
IMPORTS = ('@<% db %>.AGENTS.APP_STAGE/lib/tms_controller.zip')
HANDLER = 'run'
COMMENT = 'Human apply: write an APPROVED, non-FAIL action to APP.TASKS'
EXECUTE AS CALLER
AS
$$
from src import controller
from src.config import Config


def run(session, action_id):
    return controller.apply(session, Config("<% db %>"), action_id, controller.current_user(session))
$$;

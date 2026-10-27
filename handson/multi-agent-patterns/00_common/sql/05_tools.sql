-- 00_common/sql/05_tools.sql
-- Common foundation: read-only agent tools and owner-rights write procedures for controllers.
-- Pattern 03 creates the ASK_*_WORKER wrappers that invoke agents from another agent.
-- Custom tools for Cortex Agents and controller-only write-path procedures.
--
-- Agent-callable (read-only):   GET_TASK, SEARCH_SIMILAR_TASKS, GET_PROJECT_POLICY,
--                               VALIDATE_PROPOSED_ACTION
-- Controller-only (writes):     RECORD_VERIFICATION, DECIDE_ACTION, APPLY_APPROVED_ACTION
--
-- Write procedures run with owner's rights. The pattern role has no direct
-- INSERT/UPDATE on APP.TASKS, so every task change passes through
-- validation -> verification -> human approval -> APPLY_APPROVED_ACTION -> audit.

USE ROLE ACCOUNTADMIN;
USE WAREHOUSE <% wh %>;

CREATE SEQUENCE IF NOT EXISTS <% db %>.INTERNAL.TASK_SEQ START = 1001 INCREMENT = 1;

-------------------------------------------------------------------------------
-- GET_TASK: one task by id (read-only)
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.GET_TASK(TASK_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Read-only: return one task as JSON, or found=false'
EXECUTE AS OWNER
AS
$$
DECLARE
    res VARIANT;
BEGIN
    SELECT ARRAY_AGG(OBJECT_CONSTRUCT_KEEP_NULL(
               'task_id', TASK_ID, 'project_id', PROJECT_ID, 'title', TITLE,
               'description', DESCRIPTION, 'status', STATUS, 'priority', PRIORITY,
               'assignee', ASSIGNEE, 'due_date', TO_VARCHAR(DUE_DATE),
               'acceptance_criteria', ACCEPTANCE_CRITERIA,
               'is_overdue', (DUE_DATE < CURRENT_DATE() AND STATUS <> 'DONE')))
      INTO :res
      FROM <% db %>.APP.TASKS
     WHERE TASK_ID = UPPER(TRIM(:TASK_ID));
    IF (ARRAY_SIZE(:res) = 0) THEN
        RETURN OBJECT_CONSTRUCT('found', FALSE, 'task_id', :TASK_ID);
    END IF;
    RETURN OBJECT_INSERT(:res[0], 'found', TRUE);
END;
$$;

-------------------------------------------------------------------------------
-- SEARCH_SIMILAR_TASKS: lexical similarity within a project (read-only)
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.SEARCH_SIMILAR_TASKS(PROJECT_ID STRING, QUERY_TEXT STRING)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Read-only: top 5 tasks in a project whose title is similar to the query'
EXECUTE AS OWNER
AS
$$
DECLARE
    res VARIANT;
BEGIN
    SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
               'task_id', TASK_ID, 'title', TITLE, 'status', STATUS,
               'similarity', SIMILARITY)) WITHIN GROUP (ORDER BY SIMILARITY DESC)
      INTO :res
      FROM (
            SELECT TASK_ID, TITLE, STATUS,
                   JAROWINKLER_SIMILARITY(
                       LOWER(REGEXP_REPLACE(TITLE, '^\\[[^]]*\\]\\s*', '')),
                       LOWER(REGEXP_REPLACE(:QUERY_TEXT, '^\\[[^]]*\\]\\s*', ''))) AS SIMILARITY
              FROM <% db %>.APP.TASKS
             WHERE PROJECT_ID = UPPER(TRIM(:PROJECT_ID))
             QUALIFY ROW_NUMBER() OVER (ORDER BY SIMILARITY DESC) <= 5
           );
    RETURN OBJECT_CONSTRUCT('project_id', :PROJECT_ID, 'query', :QUERY_TEXT,
                            'candidates', COALESCE(:res, ARRAY_CONSTRUCT()),
                            'note', 'similarity is 0-100; >= 80 suggests a likely duplicate');
END;
$$;

-------------------------------------------------------------------------------
-- GET_PROJECT_POLICY (read-only)
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.GET_PROJECT_POLICY(PROJECT_ID STRING)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Read-only: project task policy'
EXECUTE AS OWNER
AS
$$
DECLARE
    res VARIANT;
BEGIN
    SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
               'project_id', PROJECT_ID, 'project_name', PROJECT_NAME,
               'title_prefix', TITLE_PREFIX,
               'require_acceptance_criteria', REQUIRE_ACCEPTANCE_CRITERIA,
               'active', ACTIVE,
               'allowed_status', ARRAY_CONSTRUCT('OPEN','IN_PROGRESS','BLOCKED','DONE'),
               'allowed_priority', ARRAY_CONSTRUCT('LOW','MEDIUM','HIGH','CRITICAL')))
      INTO :res
      FROM <% db %>.APP.PROJECTS
     WHERE PROJECT_ID = UPPER(TRIM(:PROJECT_ID));
    IF (ARRAY_SIZE(:res) = 0) THEN
        RETURN OBJECT_CONSTRUCT('found', FALSE, 'project_id', :PROJECT_ID);
    END IF;
    RETURN OBJECT_INSERT(:res[0], 'found', TRUE);
END;
$$;

-------------------------------------------------------------------------------
-- VALIDATE_PROPOSED_ACTION: deterministic checks (read-only)
-- Input: proposed-action JSON as a string (see agents/schemas/proposed-action.schema.json)
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.AGENTS.VALIDATE_PROPOSED_ACTION(ACTION_JSON STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Read-only: deterministic validation of a proposed action'
EXECUTE AS OWNER
AS
$$
import json
import re

DB = "<% db %>"
ACTION_TYPES = {"CREATE_TASK", "UPDATE_TASK", "LINK_DUPLICATE", "SKIP"}
STATUSES = {"OPEN", "IN_PROGRESS", "BLOCKED", "DONE"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
UPDATABLE = {"status", "priority", "assignee", "due_date", "acceptance_criteria"}


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def one(session, sql, params):
    rows = session.sql(sql, params=params).collect()
    return rows[0] if rows else None


def run(session, action_json):
    checks = []

    def check(name, passed, detail=""):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        return passed

    try:
        action = json.loads(action_json) if isinstance(action_json, str) else dict(action_json or {})
    except Exception as exc:
        check("parse_json", False, f"invalid JSON: {exc}")
        return {"passed": False, "checks": checks, "risk_level": "HIGH", "requires_human": True}

    action_type = str(action.get("action_type", "")).upper()
    payload = action.get("payload") or {}
    target = (action.get("target_task_id") or "").upper() or None
    evidence = action.get("evidence") or []
    risk = str(action.get("risk_level", "LOW")).upper()

    check("action_type_allowed", action_type in ACTION_TYPES, action_type)

    task_row = None
    project_id = (payload.get("project_id") or "").upper() or None
    if target:
        task_row = one(session, f"SELECT PROJECT_ID, STATUS, TITLE FROM {DB}.APP.TASKS WHERE TASK_ID = ?", [target])
        if task_row and not project_id:
            project_id = task_row["PROJECT_ID"]

    policy = None
    if project_id:
        policy = one(session, f"SELECT TITLE_PREFIX, REQUIRE_ACCEPTANCE_CRITERIA, ACTIVE FROM {DB}.APP.PROJECTS WHERE PROJECT_ID = ?", [project_id])

    if action_type == "CREATE_TASK":
        missing = [f for f in ("project_id", "title", "priority") if not payload.get(f)]
        check("required_fields", not missing, f"missing: {missing}" if missing else "ok")
        check("project_exists", policy is not None and bool(policy["ACTIVE"]), project_id or "none")
        title = payload.get("title") or ""
        if policy is not None:
            check("title_prefix", title.startswith(policy["TITLE_PREFIX"]),
                  f"title must start with {policy['TITLE_PREFIX']}")
            if policy["REQUIRE_ACCEPTANCE_CRITERIA"]:
                check("acceptance_criteria_present", bool((payload.get("acceptance_criteria") or "").strip()),
                      "project requires acceptance criteria")
            dup = one(session, f"SELECT TASK_ID FROM {DB}.APP.TASKS WHERE PROJECT_ID = ? AND LOWER(TITLE) = LOWER(?)",
                      [project_id, title])
            check("idempotency_no_same_title", dup is None, f"existing {dup['TASK_ID']}" if dup else "ok")
        if payload.get("status"):
            check("status_enum", str(payload["status"]).upper() in STATUSES, payload["status"])
        check("priority_enum", str(payload.get("priority", "")).upper() in PRIORITIES, payload.get("priority"))
    elif action_type == "UPDATE_TASK":
        check("target_exists", task_row is not None, target or "none")
        changes = {k: v for k, v in payload.items() if k != "project_id"}
        unknown = sorted(set(changes) - UPDATABLE)
        check("required_fields", bool(changes) and not unknown,
              f"unsupported fields: {unknown}" if unknown else ("ok" if changes else "no changes"))
        if "status" in changes:
            check("status_enum", str(changes["status"]).upper() in STATUSES, changes["status"])
            if str(changes["status"]).upper() == "DONE":
                risk = "HIGH"
        if "priority" in changes:
            check("priority_enum", str(changes["priority"]).upper() in PRIORITIES, changes["priority"])
            if str(changes["priority"]).upper() == "CRITICAL":
                risk = "HIGH"
        if task_row is not None and task_row["STATUS"] == "DONE" and "status" in changes:
            risk = "HIGH"
    elif action_type == "LINK_DUPLICATE":
        check("target_exists", task_row is not None, target or "none")
    elif action_type == "SKIP":
        check("required_fields", bool((action.get("reason") or "").strip()), "SKIP needs a reason")

    if action_type in {"CREATE_TASK", "UPDATE_TASK", "LINK_DUPLICATE"}:
        has_evidence = isinstance(evidence, list) and len(evidence) > 0
        check("evidence_present", has_evidence, f"{len(evidence) if isinstance(evidence, list) else 0} item(s)")
        for idx, ev in enumerate(evidence if isinstance(evidence, list) else []):
            if str(ev.get("source_type", "")).upper() == "MEETING_NOTE":
                note = one(session, f"SELECT NOTE_TEXT FROM {DB}.APP.MEETING_NOTES WHERE NOTE_ID = ?",
                           [str(ev.get("source_id", "")).upper()])
                quote = norm(ev.get("quote"))
                check(f"evidence_quote_in_source[{idx}]", note is not None and quote and quote in norm(note["NOTE_TEXT"]),
                      "quote must appear verbatim in the meeting note")

    if action.get("action_id"):
        applied = one(session, f"SELECT STATUS FROM {DB}.INTERNAL.PROPOSED_ACTIONS WHERE ACTION_ID = ?",
                      [action["action_id"]])
        check("idempotency_not_applied", applied is None or applied["STATUS"] != "APPLIED",
              applied["STATUS"] if applied else "new")

    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        risk = "HIGH"
    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "risk_level": risk,
            "requires_human": risk == "HIGH" or not passed}
$$;

-------------------------------------------------------------------------------
-- RECORD_VERIFICATION (controller-only): combine deterministic + verifier-agent results
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.RECORD_VERIFICATION(ACTION_ID STRING, AGENT_RESULT_JSON STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Controller-only: record verification and move the action to VERIFIED or REJECTED'
EXECUTE AS OWNER
AS
$$
import json
import uuid

DB = "<% db %>"

def _as_obj(value):
    return json.loads(value) if isinstance(value, str) else value


def run(session, action_id, agent_result_json):
    rows = session.sql(
        f"SELECT ACTION_ID, ACTION_TYPE, TARGET_TASK_ID, PAYLOAD, REASON, EVIDENCE, CONFIDENCE, RISK_LEVEL, STATUS "
        f"FROM {DB}.INTERNAL.PROPOSED_ACTIONS WHERE ACTION_ID = ?", params=[action_id]).collect()
    if not rows:
        return {"ok": False, "error": "action not found"}
    r = rows[0]
    if r["STATUS"] not in ("PROPOSED", "VERIFIED", "REJECTED"):
        return {"ok": False, "error": f"action is {r['STATUS']}"}
    action = {
        "action_id": r["ACTION_ID"], "action_type": r["ACTION_TYPE"], "target_task_id": r["TARGET_TASK_ID"],
        "payload": json.loads(r["PAYLOAD"]) if r["PAYLOAD"] else {}, "reason": r["REASON"],
        "evidence": json.loads(r["EVIDENCE"]) if r["EVIDENCE"] else [], "confidence": r["CONFIDENCE"],
        "risk_level": r["RISK_LEVEL"],
    }
    det = _as_obj(session.call(f"{DB}.AGENTS.VALIDATE_PROPOSED_ACTION", json.dumps(action)))
    try:
        agent = json.loads(agent_result_json) if agent_result_json else {}
    except Exception:
        agent = {"verdict": "NEEDS_HUMAN", "issues": [{"code": "UNPARSEABLE_VERIFIER_OUTPUT"}]}
    verdict = str(agent.get("verdict", "NEEDS_HUMAN")).upper()
    issues = [c for c in det["checks"] if not c["passed"]] + list(agent.get("issues") or [])
    if not det["passed"] or verdict == "FAIL":
        final = "FAIL"
    elif verdict != "PASS" or det["requires_human"]:
        final = "NEEDS_HUMAN"
    else:
        final = "PASS"
    vid = str(uuid.uuid4())
    session.sql(
        f"INSERT INTO {DB}.INTERNAL.VERIFICATION_RESULTS "
        f"(VERIFICATION_ID, ACTION_ID, DETERMINISTIC_RESULT, AGENT_RESULT, FINAL_STATUS, ISSUES) "
        f"SELECT ?, ?, PARSE_JSON(?), PARSE_JSON(?), ?, PARSE_JSON(?)",
        params=[vid, action_id, json.dumps(det), json.dumps(agent), final, json.dumps(issues)]).collect()
    new_status = "REJECTED" if final == "FAIL" else "VERIFIED"
    session.sql(f"UPDATE {DB}.INTERNAL.PROPOSED_ACTIONS SET STATUS = ?, RISK_LEVEL = ? WHERE ACTION_ID = ?",
                params=[new_status, det["risk_level"], action_id]).collect()
    session.sql(
        f"INSERT INTO {DB}.INTERNAL.AUDIT_EVENTS (EVENT_ID, RUN_ID, ACTOR, EVENT_TYPE, OBJECT_TYPE, OBJECT_ID, DETAILS) "
        f"SELECT ?, (SELECT RUN_ID FROM {DB}.INTERNAL.PROPOSED_ACTIONS WHERE ACTION_ID = ?), "
        f"'TMS_VERIFIER_AGENT', 'VERIFIED', 'PROPOSED_ACTION', ?, PARSE_JSON(?)",
        params=[str(uuid.uuid4()), action_id, action_id,
                json.dumps({"final_status": final, "issue_count": len(issues)})]).collect()
    return {"ok": True, "verification_id": vid, "final_status": final, "action_status": new_status,
            "risk_level": det["risk_level"], "issues": issues}
$$;

-------------------------------------------------------------------------------
-- DECIDE_ACTION (controller-only): human approve or discard
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.DECIDE_ACTION(ACTION_ID STRING, DECISION STRING, APPROVER STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Controller-only: record a human APPROVE or DISCARD decision'
EXECUTE AS OWNER
AS
$$
import json
import uuid

DB = "<% db %>"


def run(session, action_id, decision, approver):
    decision = (decision or "").upper()
    if decision not in ("APPROVE", "DISCARD"):
        return {"ok": False, "error": "decision must be APPROVE or DISCARD"}
    rows = session.sql(f"SELECT STATUS, RUN_ID FROM {DB}.INTERNAL.PROPOSED_ACTIONS WHERE ACTION_ID = ?",
                       params=[action_id]).collect()
    if not rows:
        return {"ok": False, "error": "action not found"}
    status = rows[0]["STATUS"]
    if decision == "APPROVE" and status != "VERIFIED":
        return {"ok": False, "error": f"only VERIFIED actions can be approved (current: {status})"}
    if status in ("APPLIED", "DISCARDED"):
        return {"ok": False, "error": f"action already {status}"}
    new_status = "APPROVED" if decision == "APPROVE" else "DISCARDED"
    session.sql(f"UPDATE {DB}.INTERNAL.PROPOSED_ACTIONS SET STATUS = ? WHERE ACTION_ID = ?",
                params=[new_status, action_id]).collect()
    session.sql(
        f"INSERT INTO {DB}.INTERNAL.AUDIT_EVENTS (EVENT_ID, RUN_ID, ACTOR, EVENT_TYPE, OBJECT_TYPE, OBJECT_ID, DETAILS) "
        f"SELECT ?, ?, ?, ?, 'PROPOSED_ACTION', ?, PARSE_JSON(?)",
        params=[str(uuid.uuid4()), rows[0]["RUN_ID"], approver or "unknown", new_status, action_id,
                json.dumps({"previous_status": status})]).collect()
    return {"ok": True, "action_status": new_status}
$$;

-------------------------------------------------------------------------------
-- APPLY_APPROVED_ACTION (controller-only): the single write path to APP.TASKS
-------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE <% db %>.INTERNAL.APPLY_APPROVED_ACTION(ACTION_ID STRING, APPROVER STRING)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
COMMENT = 'Controller-only: apply an APPROVED action idempotently and write an audit event'
EXECUTE AS OWNER
AS
$$
import json
import uuid

DB = "<% db %>"
FIELD_MAP = {"status": "STATUS", "priority": "PRIORITY", "assignee": "ASSIGNEE",
             "due_date": "DUE_DATE", "acceptance_criteria": "ACCEPTANCE_CRITERIA"}


def _as_obj(value):
    return json.loads(value) if isinstance(value, str) else value


def audit(session, run_id, actor, event_type, object_type, object_id, details):
    session.sql(
        f"INSERT INTO {DB}.INTERNAL.AUDIT_EVENTS (EVENT_ID, RUN_ID, ACTOR, EVENT_TYPE, OBJECT_TYPE, OBJECT_ID, DETAILS) "
        f"SELECT ?, ?, ?, ?, ?, ?, PARSE_JSON(?)",
        params=[str(uuid.uuid4()), run_id, actor, event_type, object_type, object_id, json.dumps(details)]).collect()


def run(session, action_id, approver):
    rows = session.sql(
        f"SELECT RUN_ID, ACTION_TYPE, TARGET_TASK_ID, PAYLOAD, REASON, EVIDENCE, CONFIDENCE, RISK_LEVEL, STATUS "
        f"FROM {DB}.INTERNAL.PROPOSED_ACTIONS WHERE ACTION_ID = ?", params=[action_id]).collect()
    if not rows:
        return {"ok": False, "error": "action not found"}
    r = rows[0]
    if r["STATUS"] == "APPLIED":
        return {"ok": True, "idempotent_replay": True, "message": "action was already applied"}
    if r["STATUS"] != "APPROVED":
        return {"ok": False, "error": f"only APPROVED actions can be applied (current: {r['STATUS']})"}
    verification = session.sql(
        f"SELECT FINAL_STATUS FROM {DB}.INTERNAL.VERIFICATION_RESULTS WHERE ACTION_ID = ? "
        f"ORDER BY CREATED_AT DESC LIMIT 1", params=[action_id]).collect()
    if not verification or verification[0]["FINAL_STATUS"] == "FAIL":
        return {"ok": False, "error": "no passing verification on record"}

    payload = json.loads(r["PAYLOAD"]) if r["PAYLOAD"] else {}
    action = {"action_id": None, "action_type": r["ACTION_TYPE"], "target_task_id": r["TARGET_TASK_ID"],
              "payload": payload, "reason": r["REASON"],
              "evidence": json.loads(r["EVIDENCE"]) if r["EVIDENCE"] else [], "risk_level": r["RISK_LEVEL"]}
    # Re-validate at apply time: data may have changed since verification.
    det = _as_obj(session.call(f"{DB}.AGENTS.VALIDATE_PROPOSED_ACTION", json.dumps(action)))
    if not det["passed"]:
        return {"ok": False, "error": "re-validation failed", "checks": det["checks"]}

    result = {"ok": True, "action_type": r["ACTION_TYPE"]}
    if r["ACTION_TYPE"] == "CREATE_TASK":
        seq = session.sql(f"SELECT {DB}.INTERNAL.TASK_SEQ.NEXTVAL AS N").collect()[0]["N"]
        task_id = f"T-{seq}"
        ev = action["evidence"][0] if action["evidence"] else {}
        session.sql(
            f"INSERT INTO {DB}.APP.TASKS (TASK_ID, PROJECT_ID, TITLE, DESCRIPTION, STATUS, PRIORITY, ASSIGNEE, "
            f"DUE_DATE, ACCEPTANCE_CRITERIA, SOURCE_TYPE, SOURCE_REF, UPDATED_AT) "
            f"SELECT ?, ?, ?, ?, ?, ?, ?, TRY_TO_DATE(?), ?, ?, ?, CURRENT_TIMESTAMP()",
            params=[task_id, payload["project_id"].upper(), payload["title"], payload.get("description"),
                    str(payload.get("status", "OPEN")).upper(), str(payload["priority"]).upper(),
                    payload.get("assignee"), payload.get("due_date"), payload.get("acceptance_criteria"),
                    str(ev.get("source_type", "REQUEST")).upper(), ev.get("source_id")]).collect()
        result["task_id"] = task_id
        audit(session, r["RUN_ID"], approver, "TASK_CREATED", "TASK", task_id, {"action_id": action_id})
    elif r["ACTION_TYPE"] == "UPDATE_TASK":
        sets, params = [], []
        for key, column in FIELD_MAP.items():
            if key in payload:
                value = payload[key]
                if key in ("status", "priority") and value is not None:
                    value = str(value).upper()
                sets.append(f"{column} = TRY_TO_DATE(?)" if key == "due_date" else f"{column} = ?")
                params.append(value)
        before = session.sql(f"SELECT OBJECT_CONSTRUCT_KEEP_NULL(*) AS O FROM {DB}.APP.TASKS WHERE TASK_ID = ?",
                             params=[r["TARGET_TASK_ID"]]).collect()[0]["O"]
        session.sql(f"UPDATE {DB}.APP.TASKS SET {', '.join(sets)}, UPDATED_AT = CURRENT_TIMESTAMP() WHERE TASK_ID = ?",
                    params=params + [r["TARGET_TASK_ID"]]).collect()
        result["task_id"] = r["TARGET_TASK_ID"]
        audit(session, r["RUN_ID"], approver, "TASK_UPDATED", "TASK", r["TARGET_TASK_ID"],
              {"action_id": action_id, "changes": payload, "before": json.loads(before)})
    elif r["ACTION_TYPE"] == "LINK_DUPLICATE":
        result["task_id"] = r["TARGET_TASK_ID"]
        audit(session, r["RUN_ID"], approver, "DUPLICATE_LINKED", "TASK", r["TARGET_TASK_ID"],
              {"action_id": action_id, "evidence": action["evidence"]})
    else:
        audit(session, r["RUN_ID"], approver, "SKIPPED", "PROPOSED_ACTION", action_id, {"reason": r["REASON"]})

    session.sql(f"UPDATE {DB}.INTERNAL.PROPOSED_ACTIONS SET STATUS = 'APPLIED' WHERE ACTION_ID = ? AND STATUS = 'APPROVED'",
                params=[action_id]).collect()
    return result
$$;

"""Contracts between the controller and the agents.

Agents return text. This module turns that text into validated Python dicts and
applies the controller's safety rules. It has no Snowflake dependency so it can
be unit-tested locally (see tests/test_contracts.py). The JSON Schemas in
agents/schemas/ describe the same shapes.
"""
from __future__ import annotations

import json
import re
from typing import Any

ALLOWED_ROUTES = ("intake", "status", "change", "human")
ACTION_TYPES = ("CREATE_TASK", "UPDATE_TASK", "LINK_DUPLICATE", "SKIP")
STATUSES = ("OPEN", "IN_PROGRESS", "BLOCKED", "DONE")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")
VERDICTS = ("PASS", "NEEDS_HUMAN", "FAIL")
IGNORE_REASONS = ("not_a_commitment", "no_owner", "undecided", "status_update", "instruction_in_data")
PAYLOAD_FIELDS = ("project_id", "title", "description", "status", "priority", "assignee", "due_date",
                  "acceptance_criteria")

# Below this router confidence the controller hands off to a human.
ROUTE_CONFIDENCE_THRESHOLD = 0.6
TASK_ID_RE = re.compile(r"\bT-\d+\b", re.IGNORECASE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ContractError(ValueError):
    """Agent output does not satisfy its contract."""


def extract_json(text: str) -> dict[str, Any]:
    """Return the first JSON object in agent text (tolerates fences and surrounding prose)."""
    if not text or not text.strip():
        raise ContractError("empty agent output")
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            value, _ = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ContractError("no JSON object found in agent output")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = "; ".join(str(v).strip() for v in value if str(v).strip())
    value = str(value).strip()
    return value or None


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(number, 0.0), 1.0)


# --------------------------------------------------------------------------- Router/Handoff
def parse_route(text: str, request_text: str = "") -> dict[str, Any]:
    """Parse and enforce the router contract. Never raises: bad output routes to human."""
    try:
        raw = extract_json(text)
    except ContractError as exc:
        return {"route": "human", "confidence": 0.0, "reason": f"router output invalid: {exc}",
                "extracted_task_ids": [], "overridden": True}
    route = str(raw.get("route", "")).strip().lower()
    confidence = _confidence(raw.get("confidence"))
    ids = raw.get("extracted_task_ids") or []
    if not isinstance(ids, list):
        ids = []
    ids = sorted({str(i).upper() for i in ids if TASK_ID_RE.fullmatch(str(i))} |
                 {m.upper() for m in TASK_ID_RE.findall(request_text or "")})
    result = {"route": route, "confidence": confidence,
              "reason": _text(raw.get("reason")) or "no reason given",
              "extracted_task_ids": ids, "overridden": False}
    if route not in ALLOWED_ROUTES:
        result.update(route="human", overridden=True, reason=f"route '{route}' is not allowed")
    elif route != "human" and confidence < ROUTE_CONFIDENCE_THRESHOLD:
        result.update(route="human", overridden=True,
                      reason=f"low confidence {confidence:.2f} < {ROUTE_CONFIDENCE_THRESHOLD}")
    elif route == "change" and len(ids) != 1:
        result.update(route="human", overridden=True,
                      reason="change requests must name exactly one task id")
    return result


# ---------------------------------------------------------------- proposed action
def normalize_action(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an agent proposal into the proposed-action contract or raise ContractError."""
    action_type = str(raw.get("action_type", "")).strip().upper()
    if action_type not in ACTION_TYPES:
        raise ContractError(f"action_type '{action_type}' is not allowed")
    payload_in = raw.get("payload") or {}
    if not isinstance(payload_in, dict):
        raise ContractError("payload must be an object")
    payload: dict[str, Any] = {}
    for key in PAYLOAD_FIELDS:
        if key in payload_in:
            value = _text(payload_in[key])
            if key in ("status", "priority") and value:
                value = value.upper().replace(" ", "_")
            if key == "project_id" and value:
                value = value.upper()
            if key == "due_date" and value and not DATE_RE.match(value):
                value = None
            if value is None and key in ("status", "priority", "title", "project_id"):
                continue
            payload[key] = value
    if action_type == "UPDATE_TASK":
        payload.pop("title", None)
    target = _text(raw.get("target_task_id"))
    target = target.upper() if target else None
    evidence = []
    for item in raw.get("evidence") or []:
        if isinstance(item, dict) and _text(item.get("quote")):
            source_type = str(item.get("source_type", "REQUEST")).upper()
            evidence.append({"source_type": source_type if source_type in ("REQUEST", "MEETING_NOTE") else "REQUEST",
                             "source_id": _text(item.get("source_id")) or "user_request",
                             "quote": _text(item.get("quote"))})
    risk = str(raw.get("risk_level", "MEDIUM")).upper()
    action = {
        "action_type": action_type,
        "target_task_id": target,
        "payload": payload,
        "reason": _text(raw.get("reason")) or "no reason given",
        "evidence": evidence,
        "confidence": _confidence(raw.get("confidence")),
        "risk_level": risk if risk in RISK_LEVELS else "HIGH",
    }
    if action_type in ("UPDATE_TASK", "LINK_DUPLICATE") and not target:
        raise ContractError(f"{action_type} requires target_task_id")
    if action_type == "CREATE_TASK":
        missing = [f for f in ("project_id", "title", "priority") if not payload.get(f)]
        if missing:
            raise ContractError(f"CREATE_TASK payload is missing {missing}")
    return action


def parse_action(text: str) -> dict[str, Any]:
    return normalize_action(extract_json(text))


# --------------------------------------------------------------------------- Orchestrator/Worker
def parse_candidates(text: str, note_id: str, project_id: str, note_text: str) -> dict[str, Any]:
    """Parse the decomposer output; drop candidates whose quote is not in the note."""
    raw = extract_json(text)
    haystack = _norm(note_text)
    candidates, ignored = [], []
    for idx, item in enumerate(raw.get("candidates") or [], start=1):
        if not isinstance(item, dict):
            continue
        quote = _text(item.get("quote"))
        title = _text(item.get("title"))
        if not quote or not title:
            continue
        if _norm(quote) not in haystack:
            ignored.append({"quote": quote, "reason": "not_a_commitment"})
            continue
        candidates.append({"candidate_id": _text(item.get("candidate_id")) or f"C{idx}", "title": title,
                           "description": _text(item.get("description")),
                           "assignee": _text(item.get("assignee")),
                           "due_hint": _text(item.get("due_hint")), "quote": quote})
    for item in raw.get("ignored") or []:
        if isinstance(item, dict) and _text(item.get("quote")):
            reason = str(item.get("reason", "not_a_commitment"))
            ignored.append({"quote": _text(item.get("quote")),
                            "reason": reason if reason in IGNORE_REASONS else "not_a_commitment"})
    return {"note_id": note_id, "project_id": project_id, "candidates": candidates, "ignored": ignored}


def parse_dedupe(text: str, candidate_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Map candidate_id -> decision. Missing or invalid decisions default to create."""
    raw = extract_json(text)
    out: dict[str, dict[str, Any]] = {}
    for item in raw.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        cid = _text(item.get("candidate_id"))
        decision = str(item.get("decision", "create")).lower()
        dup = _text(item.get("duplicate_task_id"))
        if decision == "link" and not (dup and TASK_ID_RE.fullmatch(dup)):
            decision = "create"
        if decision not in ("create", "link", "skip"):
            decision = "create"
        out[cid] = {"decision": decision, "duplicate_task_id": dup.upper() if dup and decision == "link" else None,
                    "similarity": item.get("similarity"), "reason": _text(item.get("reason")) or ""}
    for cid in candidate_ids:
        out.setdefault(cid, {"decision": "create", "duplicate_task_id": None, "similarity": None,
                             "reason": "no dedupe decision returned"})
    return out


def parse_criteria(text: str) -> dict[str, dict[str, Any]]:
    raw = extract_json(text)
    out = {}
    for item in raw.get("items") or []:
        if isinstance(item, dict) and _text(item.get("candidate_id")):
            priority = str(item.get("priority", "MEDIUM")).upper()
            out[_text(item.get("candidate_id"))] = {
                "title": _text(item.get("title")),
                "priority": priority if priority in PRIORITIES else "MEDIUM",
                "acceptance_criteria": _text(item.get("acceptance_criteria")),
            }
    return out


# Orchestrator/Worker wiring (APP.WORKER_PLAN). The controller calls only allowlisted workers, and a worker
# request may use only these placeholders: the note text is deliberately not available to workers.
WORKER_AGENTS = {"dedupe": "TMS_DEDUPE_AGENT", "criteria": "TMS_CRITERIA_AGENT"}
REQUEST_PLACEHOLDERS = {"project_id", "note_id", "candidates_json"}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_]+)\}")


def render_worker_request(worker: str, agent_name: str, template: str, values: dict[str, str]) -> str:
    """Validate one WORKER_PLAN row and return the request text the worker receives."""
    worker = (worker or "").strip().lower()
    if worker not in WORKER_AGENTS:
        raise ContractError(f"unknown worker {worker!r}; allowed: {sorted(WORKER_AGENTS)}")
    if (agent_name or "").strip().upper() != WORKER_AGENTS[worker]:
        raise ContractError(f"worker {worker!r} must call {WORKER_AGENTS[worker]}, not {agent_name!r}")
    template = template or ""
    if "..." in template:
        raise ContractError("request template still contains ...")
    used = set(_PLACEHOLDER.findall(template))
    if used - REQUEST_PLACEHOLDERS:
        raise ContractError(f"placeholder(s) not allowed: {sorted(used - REQUEST_PLACEHOLDERS)}; "
                            f"allowed: {sorted(REQUEST_PLACEHOLDERS)}")
    if "candidates_json" not in used:
        raise ContractError("request template must contain {candidates_json}")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def build_note_actions(package: dict[str, Any], dedupe: dict[str, dict[str, Any]],
                       criteria: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregation: combine worker outputs into proposed actions (one per candidate)."""
    actions = []
    for cand in package["candidates"]:
        cid = cand["candidate_id"]
        dd = dedupe.get(cid, {"decision": "create"})
        crit = criteria.get(cid, {})
        evidence = [{"source_type": "MEETING_NOTE", "source_id": package["note_id"], "quote": cand["quote"]}]
        if dd["decision"] == "link":
            actions.append({"action_type": "LINK_DUPLICATE", "target_task_id": dd["duplicate_task_id"],
                            "payload": {"project_id": package["project_id"]},
                            "reason": f"Duplicate of {dd['duplicate_task_id']}: {dd.get('reason', '')}".strip(),
                            "evidence": evidence, "confidence": 0.8, "risk_level": "LOW"})
        elif dd["decision"] == "skip":
            actions.append({"action_type": "SKIP", "target_task_id": None,
                            "payload": {"project_id": package["project_id"]},
                            "reason": dd.get("reason") or "not actionable", "evidence": evidence,
                            "confidence": 0.7, "risk_level": "LOW"})
        else:
            payload = {"project_id": package["project_id"], "title": crit.get("title") or cand["title"],
                       "description": cand.get("description"), "priority": crit.get("priority", "MEDIUM"),
                       "assignee": cand.get("assignee"), "due_date": None,
                       "acceptance_criteria": crit.get("acceptance_criteria")}
            actions.append({"action_type": "CREATE_TASK", "target_task_id": None, "payload": payload,
                            "reason": f"Explicit commitment in {package['note_id']}", "evidence": evidence,
                            "confidence": 0.8, "risk_level": "LOW"})
    return [normalize_action(a) for a in actions]


# --------------------------------------------------------------------------- Verifier
def parse_verification(text: str) -> dict[str, Any]:
    """Parse verifier output. Unparseable output becomes NEEDS_HUMAN (fail safe, never PASS)."""
    try:
        raw = extract_json(text)
    except ContractError as exc:
        return {"verdict": "NEEDS_HUMAN", "issues": [{"code": "UNPARSEABLE_VERIFIER_OUTPUT", "message": str(exc)}],
                "checked": []}
    verdict = str(raw.get("verdict", "NEEDS_HUMAN")).upper()
    issues = []
    for item in raw.get("issues") or []:
        if isinstance(item, dict):
            code = re.sub(r"[^A-Z0-9_]", "_", str(item.get("code", "ISSUE")).upper()) or "ISSUE"
            issues.append({"code": code, "message": _text(item.get("message")) or ""})
        elif _text(item):
            issues.append({"code": "ISSUE", "message": _text(item)})
    checked = [str(c) for c in raw.get("checked") or []] if isinstance(raw.get("checked"), list) else []
    return {"verdict": verdict if verdict in VERDICTS else "NEEDS_HUMAN", "issues": issues, "checked": checked}


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

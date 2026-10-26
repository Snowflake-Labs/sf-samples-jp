"""Run trace and proposal persistence. The workshop role may only INSERT here;
status changes go through owner's-rights procedures in the INTERNAL schema."""
from __future__ import annotations

import json
import uuid
from typing import Any

from . import db
from .config import Config

MAX_SUMMARY = 1500


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _clip(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_SUMMARY else text[:MAX_SUMMARY] + "..."


class RunTrace:
    """Writes one RUN_EVENTS row per controller step for a single run."""

    def __init__(self, session, cfg: Config, pattern: str, run_id: str | None = None):
        self.session, self.cfg, self.pattern = session, cfg, pattern
        self.run_id = run_id or new_id("RUN")
        self.step_no = 0
        self.steps: list[dict[str, Any]] = []

    def step(self, agent_name: str, input_summary: Any, output_summary: Any, status: str,
             elapsed_ms: int = 0, pattern: str | None = None) -> None:
        self.step_no += 1
        row = {"step_no": self.step_no, "pattern": pattern or self.pattern, "agent_name": agent_name,
               "input_summary": _clip(input_summary), "output_summary": _clip(output_summary),
               "status": status, "elapsed_ms": int(elapsed_ms)}
        self.steps.append(row)
        db.execute(self.session,
                   f"INSERT INTO {self.cfg.internal('RUN_EVENTS')} (RUN_ID, STEP_NO, PATTERN, AGENT_NAME, "
                   f"INPUT_SUMMARY, OUTPUT_SUMMARY, STATUS, ELAPSED_MS) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   [self.run_id, row["step_no"], row["pattern"], agent_name, row["input_summary"],
                    row["output_summary"], status, row["elapsed_ms"]])


def insert_proposal(session, cfg: Config, run_id: str, action: dict[str, Any]) -> str:
    action_id = new_id("ACT")
    db.execute(session,
               f"INSERT INTO {cfg.internal('PROPOSED_ACTIONS')} (ACTION_ID, RUN_ID, ACTION_TYPE, TARGET_TASK_ID, "
               f"PAYLOAD, REASON, EVIDENCE, CONFIDENCE, RISK_LEVEL, STATUS) "
               f"SELECT ?, ?, ?, ?, PARSE_JSON(?), ?, PARSE_JSON(?), ?, ?, 'PROPOSED'",
               [action_id, run_id, action["action_type"], action.get("target_task_id"),
                json.dumps(action["payload"], ensure_ascii=False), action["reason"],
                json.dumps(action["evidence"], ensure_ascii=False), float(action["confidence"]),
                action["risk_level"]])
    return action_id

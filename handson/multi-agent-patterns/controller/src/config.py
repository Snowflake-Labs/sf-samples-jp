"""Runtime configuration. Each controller procedure passes its database name to Config."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE = "MULTI_AGENT_PATTERNS"
AGENT_NAMES = {
    "router": "TMS_ROUTER_AGENT",
    "intake": "TMS_INTAKE_AGENT",
    "status": "TMS_STATUS_AGENT",
    "change": "TMS_CHANGE_AGENT",
    "decomposer": "TMS_DECOMPOSER_AGENT",
    "dedupe": "TMS_DEDUPE_AGENT",
    "criteria": "TMS_CRITERIA_AGENT",
    "verifier": "TMS_VERIFIER_AGENT",
    "orchestrator": "TMS_ORCHESTRATOR_AGENT",
}


@dataclass(frozen=True)
class Config:
    database: str

    def agent(self, key: str) -> str:
        return f"{self.database}.AGENTS.{AGENT_NAMES[key]}"

    def app(self, table: str) -> str:
        return f"{self.database}.APP.{table}"

    def internal(self, name: str) -> str:
        return f"{self.database}.INTERNAL.{name}"

    def tool(self, name: str) -> str:
        return f"{self.database}.AGENTS.{name}"


def load(session=None) -> Config:
    database = os.environ.get("MAP_DATABASE")
    if not database and session is not None:
        try:
            database = session.get_current_database()
        except Exception:  # pragma: no cover - defensive for local sessions
            database = None
    return Config(database=(database or DEFAULT_DATABASE).strip('"').upper())

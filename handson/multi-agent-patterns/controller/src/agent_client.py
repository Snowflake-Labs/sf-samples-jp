"""Thin client for Cortex Agents through SNOWFLAKE.CORTEX.DATA_AGENT_RUN (non-streaming).

Thinking blocks are dropped: the app never shows chain-of-thought. Tool calls are
kept (name + input) so that the Trace view can show what each agent did.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    agent: str
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def tool_summary(self) -> str:
        return ", ".join(c["name"] for c in self.tool_calls) or "no tools"


def parse_response(agent: str, response: Any, elapsed_ms: int = 0) -> AgentResult:
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            return AgentResult(agent, "", elapsed_ms=elapsed_ms, error="agent returned non-JSON response")
    response = response or {}
    if "code" in response and "content" not in response:
        return AgentResult(agent, "", elapsed_ms=elapsed_ms,
                           error=f"{response.get('code')}: {response.get('message', 'agent error')}")
    texts, tools, tables = [], [], []
    for item in response.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            texts.append(item.get("text", ""))
        elif kind == "tool_use":
            use = item.get("tool_use", {})
            tools.append({"name": use.get("name"), "input": use.get("input")})
        elif kind == "table":
            tables.append(item.get("table", {}))
    return AgentResult(agent=agent, text="".join(texts).strip(), tool_calls=tools, tables=tables,
                       warnings=response.get("warnings") or [], elapsed_ms=elapsed_ms)


def run_agent(session, agent_fqn: str, text: str) -> AgentResult:
    """Run one agent turn. Errors are returned in AgentResult.error, never raised."""
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": text}]}]}
    started = time.time()
    try:
        row = session.sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS R",
                          params=[agent_fqn, json.dumps(body)]).collect()[0]
        elapsed = int((time.time() - started) * 1000)
        return parse_response(agent_fqn.split(".")[-1], row["R"], elapsed)
    except Exception as exc:  # surfaced in the UI and the trace
        elapsed = int((time.time() - started) * 1000)
        return AgentResult(agent_fqn.split(".")[-1], "", elapsed_ms=elapsed, error=str(exc)[:500])

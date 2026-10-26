"""Query helpers for the controller procedures. All SQL uses bind parameters."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd


def query_df(session, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    return session.sql(sql, params=params or []).to_pandas()


def query_rows(session, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    return [row.as_dict() for row in session.sql(sql, params=params or []).collect()]


def execute(session, sql: str, params: list[Any] | None = None) -> None:
    session.sql(sql, params=params or []).collect()


def call(session, procedure: str, *args: Any) -> dict[str, Any]:
    """Call a VARIANT-returning procedure and return the parsed JSON."""
    result = session.call(procedure, *args)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"raw": result}
    return result or {}


def variant(value: Any) -> Any:
    """Parse a VARIANT column value returned as a JSON string."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value

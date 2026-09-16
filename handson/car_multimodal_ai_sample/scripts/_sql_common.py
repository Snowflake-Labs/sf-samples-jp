"""Shared helper for executing plain .sql files via a Snowpark session.

car_multimodal_ai_sample's `infra/*.sql` scripts are plain multi-statement SQL
(no stored procedures, no `;` inside string literals or comments), so a simple
comment-strip + split-on-`;` is enough to run them programmatically instead of
pasting them into a Snowsight Worksheet by hand.
"""

from __future__ import annotations

from pathlib import Path


def run_sql_file(session, path: Path, echo: bool = True) -> list:
    """Execute every statement in a .sql file in order.

    Strips `--` line comments before splitting on `;`. Returns the list of
    result row-lists, one per executed statement (in file order).
    """
    text = path.read_text()
    kept_lines = [line for line in text.splitlines() if not line.strip().startswith("--")]
    statements = [s.strip() for s in "\n".join(kept_lines).split(";")]
    statements = [s for s in statements if s]

    results = []
    for stmt in statements:
        if echo:
            first_line = stmt.splitlines()[0][:100]
            print(f">>> {first_line}")
        rows = session.sql(stmt).collect()
        results.append(rows)
        if echo and rows:
            for row in rows[:20]:
                print(f"    {row}")
    return results

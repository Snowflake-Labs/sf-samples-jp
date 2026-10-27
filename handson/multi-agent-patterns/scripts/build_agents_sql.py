#!/usr/bin/env python3
"""各パターンの agents/*.yaml（正本）から sql/10_agents.sql を生成する。

Usage: python3 scripts/build_agents_sql.py [--check]
--check: 生成物が古ければ非 0 で終了する（tests から使う）。
"""
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATTERNS = {
    "01_router_handoff": ["router", "intake", "status", "change"],
    "02_orchestrator_worker": ["decomposer", "dedupe", "criteria"],
    "03_agent_as_tool": ["orchestrator"],
    "04_verifier_human_in_the_loop": ["verifier"],
    "07_parallel_fanout": ["schedule_reviewer", "ownership_reviewer", "quality_reviewer"],
}


def render(pattern: str, names: list[str]) -> str:
    out = [
        f"-- {pattern}/sql/10_agents.sql",
        "-- 自動生成: scripts/build_agents_sql.py が agents/*.yaml から生成。YAML を編集して再生成すること。",
        "-- どのエージェントにも書き込みツールはない（書き込みは承認後の所有者権限プロシージャのみ）。",
        "",
        "USE ROLE ACCOUNTADMIN;",
        "USE WAREHOUSE <% wh %>;",
        "",
    ]
    for name in names:
        text = (ROOT / pattern / "agents" / f"{name}.yaml").read_text()
        yaml.safe_load(text)  # 不正な YAML は即失敗
        lines = text.splitlines()
        display = lines[0].lstrip("# ")
        comment = lines[1].lstrip("# ").replace("'", "''")
        body = "\n".join(line for line in lines if not line.startswith("#"))
        out += [
            f"CREATE OR REPLACE AGENT <% db %>.AGENTS.TMS_{name.upper()}_AGENT",
            f"    COMMENT = '{comment}'",
            f"    PROFILE = '{{\"display_name\": \"{display}\"}}'",
            "    FROM SPECIFICATION",
            "$$",
            body.strip(),
            "$$;",
            "",
        ]
    return "\n".join(out) + "\n"


def main() -> int:
    stale = []
    for pattern, names in PATTERNS.items():
        target = ROOT / pattern / "sql" / "10_agents.sql"
        content = render(pattern, names)
        if "--check" in sys.argv:
            if not target.exists() or target.read_text() != content:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(content)
            print(f"wrote {target.relative_to(ROOT)}")
    if stale:
        print("out of date (run scripts/build_agents_sql.py): " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

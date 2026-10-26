#!/usr/bin/env python3
"""パターン 06: P0〜P4 を N 回ずつ実行し、どのスキル本文が回答に反映されたかを判定する。

P-ALPHA-3141 は親スキル本文だけ、C-BRAVO-2718 はサブスキル（house style）本文だけにある。
description には含まれないので、回答にコードがあれば、その SKILL.md 本文を読み込んだことになる。
Usage: python3 run_patterns.py -c <connection> [-n 3]
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import agent_runner as ar  # noqa: E402

args = ar.parse_args("Run every skill composition pattern N times.", "MAP_SKILL_DATABASE", "MAP_SKILL_COMPOSITION")
PROMPT = "Write a status report about the Q3 data migration project."
CONTROL = ("Format this draft status report: The Q3 data migration moved 12 tables. "
           "Validation is next. The legacy job may run late.")
CASES = [
    ("P0_CONTROL_AGENT", CONTROL, "child skill alone (control)"),
    ("P1_PEER_AGENT", PROMPT, "parent + child as peer skills; parent tells agent to use child"),
    ("P2_NESTED_AGENT", PROMPT, "parent only; child SKILL.md in parent subfolder"),
    ("P3_COMBINED_AGENT", PROMPT, "one skill with both parts"),
    ("P4_SUBAGENT_AGENT", PROMPT, "parent skill -> procedure tool -> FORMATTER_AGENT (child skill)"),
]
out, stamp = ar.results_dir(__file__)
summary = []
for agent, prompt, label in CASES:
    for i in range(1, args.runs + 1):
        resp, size, secs = ar.run_agent(args, agent, prompt)
        ar.save(out, f"{stamp}_{agent}_{i}.json", resp)
        if "content" not in resp:
            row = dict(agent=agent, run=i, seconds=secs, error=str(resp.get("error") or resp.get("message") or resp)[:300])
        else:
            text, tools, _ = ar.summarize(resp)
            row = dict(agent=agent, label=label, run=i, seconds=secs, parent_code="P-ALPHA-3141" in text,
                       child_code="C-BRAVO-2718" in text, house_style="## Status report" in text,
                       tool_calls=tools, answer=text[:400])
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False))
ar.save(out, f"{stamp}_summary.json", summary)
print(f"\nSaved results/{stamp}_summary.json")

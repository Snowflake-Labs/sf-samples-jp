#!/usr/bin/env python3
"""Run pattern 05 cases M0-M3 N times and detect whether calls reached the child agent.

M-CHILD-5501 appears only in CHILD_AGENT instructions, while M-MID-7702 appears only in
MIDDLE_AGENT instructions. child_code and middle_code report whether the code words remain in the
parent's final answer. child_reached checks the entire response, including tool results, to verify
that the request reached the child.
Usage: python3 run_patterns.py -c <connection> [-n 3]
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import agent_runner as ar  # noqa: E402

args = ar.parse_args("Run every MCP chaining pattern N times.", "MAP_MCP_DATABASE", "MAP_MCP_CHAIN")
PROMPT = "Write a status report about the Q3 data migration project."
CONTROL = "Format this draft: The Q3 data migration moved 12 tables. Validation is next. The legacy job may run late."
CASES = [
    ("CHILD_AGENT", CONTROL, "M0 control: child agent called directly"),
    ("M1_PARENT_MCP_AGENT", PROMPT, "M1: parent -> CHILD_MCP -> child"),
    ("M2_PARENT_TWO_HOP_AGENT", PROMPT, "M2: parent -> MIDDLE_MCP -> middle -> CHILD_MCP -> child"),
    ("M3_PARENT_PROCEDURE_AGENT", PROMPT, "M3 baseline: parent -> procedure tool -> child"),
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
            text, tools, results = ar.summarize(resp)
            row = dict(agent=agent, label=label, run=i, seconds=secs, response_bytes=size,
                       child_code="M-CHILD-5501" in text, middle_code="M-MID-7702" in text,
                       child_reached="M-CHILD-5501" in json.dumps(resp), house_style="## Status report" in text,
                       tool_calls=tools, tool_results=results,
                       answer=text[:300])
        summary.append(row)
        print(json.dumps(row, ensure_ascii=False))
ar.save(out, f"{stamp}_summary.json", summary)
print(f"\nSaved results/{stamp}_summary.json")

#!/usr/bin/env bash
# setup_all.sh - 00_common と全パターン（01〜08）を順に作成する（08 は 02 のエージェントを使うので後ろ）。
# Usage: scripts/setup_all.sh -c <connection>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for p in 00_common 01_router_handoff 02_orchestrator_worker 03_agent_as_tool 04_verifier_human_in_the_loop \
         05_mcp_agent_chaining 06_skill_composition 07_parallel_fanout 08_blackboard; do
  echo "######## $p"
  "$ROOT/$p/setup.sh" "$@"
done

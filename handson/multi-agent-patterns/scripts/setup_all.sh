#!/usr/bin/env bash
# setup_all.sh - 00_common と全パターン（01〜06）を順に作成する。
# Usage: scripts/setup_all.sh -c <connection>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for p in 00_common 01_router_handoff 02_orchestrator_worker 03_agent_as_tool 04_verifier_human_in_the_loop \
         05_mcp_agent_chaining 06_skill_composition; do
  echo "######## $p"
  "$ROOT/$p/setup.sh" "$@"
done

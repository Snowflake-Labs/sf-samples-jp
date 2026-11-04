#!/usr/bin/env bash
# setup_all.sh - Create 00_common and patterns 01-08 in dependency order; 08 reuses agents from 02.
# Usage: scripts/setup_all.sh -c <connection>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for p in 00_common 01_router_handoff 02_orchestrator_worker 03_agent_as_tool 04_verifier_human_in_the_loop \
         05_mcp_agent_chaining 06_skill_composition 07_parallel_fanout 08_blackboard; do
  echo "######## $p"
  "$ROOT/$p/setup.sh" "$@"
done

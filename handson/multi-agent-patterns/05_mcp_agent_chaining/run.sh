#!/usr/bin/env bash
# 05_mcp_agent_chaining/run.sh - Run run_patterns.py; use -n to override the default three iterations.
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
python3 "$MAP_ROOT/05_mcp_agent_chaining/run_patterns.py" -c "$CONN" -n "$RUNS"

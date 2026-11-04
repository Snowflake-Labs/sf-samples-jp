#!/usr/bin/env bash
# 08_blackboard/setup.sh - Create an idempotent event-driven blackboard with streams and triggered tasks.
# Requires 00_common and pattern 02 agents: Decomposer, Dedupe, and Criteria.
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/08_blackboard"
require_common
require_agents TMS_DECOMPOSER_AGENT TMS_DEDUPE_AGENT TMS_CRITERIA_AGENT   # Reuse pattern 02 agents.
deploy_controller        # Rebuild the controller ZIP with the latest board.py.
run_sql "$HERE/sql/20_objects.sql"
run_sql "$HERE/sql/22_react.sql"
run_sql "$HERE/sql/25_tasks.sql"
run_sql "$HERE/sql/28_entry.sql"
run_sql "$HERE/sql/30_grants.sql"
echo "Setup complete. Next: ./run.sh -c ${CONN}  （または sql/90_try.sql を Snowsight で実行）"

#!/usr/bin/env bash
# 07_parallel_fanout/setup.sh - Create an idempotent fan-out/fan-in task graph; requires 00_common.
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/07_parallel_fanout"
require_common
if python3 -c "import yaml" 2>/dev/null; then
  python3 "$MAP_ROOT/scripts/build_agents_sql.py" --check >/dev/null || die "sql/10_agents.sql が agents/*.yaml と一致しません: python3 scripts/build_agents_sql.py"
fi
deploy_controller        # Rebuild the controller ZIP with the latest review.py.
run_sql "$HERE/sql/10_agents.sql"
run_sql "$HERE/sql/20_objects.sql"
run_sql "$HERE/sql/25_tasks.sql"
run_sql "$HERE/sql/28_entry.sql"
run_sql "$HERE/sql/30_grants.sql"
echo "Setup complete. Next: ./run.sh -c ${CONN}  （または sql/90_try.sql を Snowsight で実行）"

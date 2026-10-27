#!/usr/bin/env bash
# 02_orchestrator_worker/setup.sh - Create this pattern's agents and procedures; requires 00_common and is idempotent.
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/02_orchestrator_worker"
require_common

# Detect stale generated SQL after editing agents/*.yaml; skip when PyYAML is unavailable.
if python3 -c "import yaml" 2>/dev/null; then
  python3 "$MAP_ROOT/scripts/build_agents_sql.py" --check >/dev/null || die "sql/10_agents.sql が agents/*.yaml と一致しません: python3 scripts/build_agents_sql.py"
fi
run_sql "$HERE/sql/10_agents.sql"
run_sql "$HERE/sql/20_procedures.sql"
run_sql "$HERE/sql/30_grants.sql"
echo "Setup complete. Next: ./run.sh -c $CONN  （または sql/90_try.sql を Snowsight で実行）"

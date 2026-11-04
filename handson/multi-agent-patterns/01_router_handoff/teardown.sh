#!/usr/bin/env bash
# 01_router_handoff/teardown.sh - Delete only this pattern's agents and procedures; keep the common foundation.
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "01_router_handoff のエージェントとプロシージャ（$DB 内）"
run_sql "$MAP_ROOT/01_router_handoff/sql/99_teardown.sql"
echo "Teardown complete."

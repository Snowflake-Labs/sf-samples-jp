#!/usr/bin/env bash
# 01_router_handoff/teardown.sh - このパターンのエージェントとプロシージャだけを削除（共通基盤は残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "01_router_handoff のエージェントとプロシージャ（$DB 内）"
run_sql "$MAP_ROOT/01_router_handoff/sql/99_teardown.sql"
echo "Teardown complete."

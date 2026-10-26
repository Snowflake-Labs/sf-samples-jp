#!/usr/bin/env bash
# 03_agent_as_tool/teardown.sh - このパターンのエージェントとプロシージャだけを削除（共通基盤は残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "03_agent_as_tool のエージェントとプロシージャ（$DB 内）"
run_sql "$MAP_ROOT/03_agent_as_tool/sql/99_teardown.sql"
echo "Teardown complete."

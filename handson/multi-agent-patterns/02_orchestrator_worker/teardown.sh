#!/usr/bin/env bash
# 02_orchestrator_worker/teardown.sh - このパターンのエージェントとプロシージャだけを削除（共通基盤は残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "02_orchestrator_worker のエージェントとプロシージャ（$DB 内）"
run_sql "$MAP_ROOT/02_orchestrator_worker/sql/99_teardown.sql"
echo "Teardown complete."

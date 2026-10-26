#!/usr/bin/env bash
# 00_common/teardown.sh - 共通基盤とパターン 01-04 のすべて（DB）、ウェアハウス、ロールを削除。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
guard_names "$DB" "$WH" "$ROLE"
confirm_or_exit "DATABASE  $DB" "WAREHOUSE ${WH}（パターン 05/06 も使う共通ウェアハウス）" "ROLE      $ROLE"
run_sql "$MAP_ROOT/00_common/sql/99_teardown.sql"
echo "Teardown complete."

#!/usr/bin/env bash
# 07_parallel_fanout/teardown.sh - Delete this pattern's objects only; keep the common foundation.
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "07_parallel_fanout のタスクグラフ・エージェント・プロシージャ・テーブル・ビュー（${DB} 内）"
run_sql "$MAP_ROOT/07_parallel_fanout/sql/99_teardown.sql"
echo "Teardown complete."

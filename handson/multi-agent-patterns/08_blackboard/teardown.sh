#!/usr/bin/env bash
# 08_blackboard/teardown.sh - このパターンのタスク・ストリーム・プロシージャ・テーブル・ビューだけを削除（共通基盤は残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "08_blackboard のトリガータスク・ストリーム・プロシージャ・テーブル・ビュー（${DB} 内）"
run_sql "$MAP_ROOT/08_blackboard/sql/99_teardown.sql"
echo "Teardown complete."

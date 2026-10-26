#!/usr/bin/env bash
# 06_skill_composition/teardown.sh - パターン 06 のデータベースだけを削除（共通ウェアハウスは残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
guard_names "$SKILL_DB"
confirm_or_exit "DATABASE ${SKILL_DB}（エージェント 6、スキルのステージ、プロシージャ 1）"
run_sql "$MAP_ROOT/06_skill_composition/sql/99_teardown.sql"
echo "Teardown complete."

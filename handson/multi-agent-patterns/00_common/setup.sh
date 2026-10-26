#!/usr/bin/env bash
# 00_common/setup.sh - パターン 01-04 の共通基盤を作成（再実行可能）。
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/00_common"
preflight
run_sql "$HERE/sql/01_account.sql"
run_sql "$HERE/sql/02_tables.sql"
run_sql "$HERE/sql/03_seed.sql"
run_sql "$HERE/sql/04_semantic_view.sql"
run_sql "$HERE/sql/05_tools.sql"
info "Uploading controller/src/*.py to @$DB.AGENTS.APP_STAGE/lib/src"
find "$MAP_ROOT/controller" -name "__pycache__" -type d -prune -exec rm -rf {} +
for f in "$MAP_ROOT"/controller/src/*.py; do
  snow stage copy -c "$CONN" "$f" "@$DB.AGENTS.APP_STAGE/lib/src" --overwrite >/dev/null 2>&1 || die "upload of $f failed"
done
run_sql "$HERE/sql/06_controller.sql"
run_sql "$HERE/sql/08_grants.sql"
run_sql "$HERE/sql/09_smoke_tests.sql"
info "Smoke tests passed"

# Cortex Agents は既定ウェアハウスを必要とする。未設定なら案内だけ出す（ユーザー設定は変更しない）。
USR="$(sqlq "SELECT CURRENT_USER() AS U")"; USER_NAME="$(jfield "$USR" "d[0]['U']")"
DESC="$(sqlq "DESC USER IDENTIFIER('\"$USER_NAME\"')")"
DEF_WH="$(jfield "$DESC" "next((r['value'] for r in d if r['property']=='DEFAULT_WAREHOUSE'), 'null')")"
if [[ "$DEF_WH" == "null" || -z "$DEF_WH" ]]; then
  echo "WARNING: ユーザーに既定ウェアハウスがありません。エージェント実行に必要です。例:"
  echo "         ALTER USER <your_user> SET DEFAULT_WAREHOUSE = $WH;"
fi
echo "Common setup complete: database $DB, warehouse $WH, role $ROLE. Next: ../01_router_handoff/setup.sh"

#!/usr/bin/env bash
# 00_common/setup.sh - Create the idempotent common foundation for patterns 01-04.
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
info "Uploading controller/src/*.py to @${DB}.AGENTS.APP_STAGE/lib/src"
find "$MAP_ROOT/controller" -name "__pycache__" -type d -prune -exec rm -rf {} +
for f in "$MAP_ROOT"/controller/src/*.py; do
  put_file "$f" "@${DB}.AGENTS.APP_STAGE/lib/src/" || die "upload of $f failed"
done
# 06_controller.sql creates and runs BUILD_CONTROLLER_ZIP; later patterns refresh it through deploy_controller.
run_sql "$HERE/sql/06_controller.sql"
run_sql "$HERE/sql/08_grants.sql"
run_sql "$HERE/sql/09_smoke_tests.sql"
info "Smoke tests passed"

# Cortex Agents require a default warehouse. Print guidance when absent; never alter the user.
USR="$(sqlq "SELECT CURRENT_USER() AS U")"; USER_NAME="$(jfield "$USR" "d[0]['U']")"
DESC="$(sqlq "DESC USER IDENTIFIER('\"$USER_NAME\"')")"
DEF_WH="$(jfield "$DESC" "next((r['value'] for r in d if r['property']=='DEFAULT_WAREHOUSE'), 'null')")"
if [[ "$DEF_WH" == "null" || -z "$DEF_WH" ]]; then
  echo "WARNING: ユーザーに既定ウェアハウスがありません。エージェント実行に必要です。例:"
  echo "         ALTER USER <your_user> SET DEFAULT_WAREHOUSE = $WH;"
fi
echo "Common setup complete: database $DB, warehouse $WH, role $ROLE. Next: ../01_router_handoff/setup.sh"

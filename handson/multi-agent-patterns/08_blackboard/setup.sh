#!/usr/bin/env bash
# 08_blackboard/setup.sh - ブラックボード／イベント駆動（ストリーム + トリガータスク）を作成（再実行可能）。
# 00_common と 02（Decomposer / Dedupe / Criteria エージェント）が前提。
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/08_blackboard"
require_common
require_agents TMS_DECOMPOSER_AGENT TMS_DEDUPE_AGENT TMS_CRITERIA_AGENT   # 02 のエージェントを再利用
deploy_controller        # board.py を含む最新のコントローラを zip に反映
run_sql "$HERE/sql/20_objects.sql"
run_sql "$HERE/sql/22_react.sql"
run_sql "$HERE/sql/25_tasks.sql"
run_sql "$HERE/sql/28_entry.sql"
run_sql "$HERE/sql/30_grants.sql"
echo "Setup complete. Next: ./run.sh -c ${CONN}  （または sql/90_try.sql を Snowsight で実行）"

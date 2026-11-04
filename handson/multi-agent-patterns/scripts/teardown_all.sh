#!/usr/bin/env bash
# teardown_all.sh - Delete everything created by this project in reverse dependency order.
#   08 -> 07 -> 04 -> 03 -> 02 -> 01 (tasks, agents, and procedures in the common database)
#   -> 06 -> 05 (dedicated databases) -> 00_common (common database, warehouse, and role)
# Always run 05, 06, and 00_common because they use DROP ... IF EXISTS. Skip 01-04 if the common database is absent.
# This script is idempotent and checks for leftovers at the end.
# Usage: scripts/teardown_all.sh -c <connection> --confirm
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
map_init "$@"
guard_names "$DB" "$WH" "$ROLE" "$MCP_DB" "$SKILL_DB"

echo "全体の teardown（接続先のオブジェクト名）:"
printf '  %s\n' "パターン 01〜04・07・08: ${DB} 内のタスク・エージェント・プロシージャ・テーブル" \
  "パターン 05: DATABASE ${MCP_DB}" "パターン 06: DATABASE ${SKILL_DB}" \
  "00_common: DATABASE ${DB}, WAREHOUSE ${WH}, ROLE ${ROLE}"
$CONFIRM || { echo "何も削除していません。--confirm を付けて再実行してください。"; exit 1; }

db_exists() {  # 一時的な接続エラーで誤判定しないよう 1 回だけ再試行する
  local out
  out="$(sqlq "SHOW DATABASES LIKE '$1'")" || { sleep 5; out="$(sqlq "SHOW DATABASES LIKE '$1'")"; } || return 1
  [[ "$(jfield "$out" "len(d)")" != "0" ]]
}

run_teardown() {  # run_teardown <pattern>
  echo "######## $1"
  "$MAP_ROOT/$1/teardown.sh" -c "$CONN" --confirm >/dev/null || die "$1 の teardown に失敗しました（再実行できます）"
  echo "==> $1: done"
}

if db_exists "$DB"; then
  for p in 08_blackboard 07_parallel_fanout 04_verifier_human_in_the_loop 03_agent_as_tool 02_orchestrator_worker 01_router_handoff; do
    run_teardown "$p"
  done
else
  echo "==> 01〜04・07・08: ${DB} が無いのでスキップ（00_common の teardown で DB ごと削除される）"
fi
run_teardown 06_skill_composition
run_teardown 05_mcp_agent_chaining
run_teardown 00_common

# Check for objects that were not removed.
left=""
for d in "$DB" "$MCP_DB" "$SKILL_DB"; do db_exists "$d" && left="$left DATABASE:$d"; done
out="$(sqlq "SHOW WAREHOUSES LIKE '$WH'")" && [[ "$(jfield "$out" "len(d)")" != "0" ]] && left="$left WAREHOUSE:$WH"
out="$(sqlq "SHOW ROLES LIKE '$ROLE'")" && [[ "$(jfield "$out" "len(d)")" != "0" ]] && left="$left ROLE:$ROLE"
[[ -z "$left" ]] || die "削除できなかったオブジェクトがあります:${left}（もう一度実行してください）"

echo "All teardown complete."

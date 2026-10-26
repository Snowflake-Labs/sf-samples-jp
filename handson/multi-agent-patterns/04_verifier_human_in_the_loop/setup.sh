#!/usr/bin/env bash
# 04_verifier_human_in_the_loop/setup.sh - このパターンのエージェントとプロシージャを作成（再実行可能）。00_common が前提。
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/04_verifier_human_in_the_loop"
require_common

# agents/*.yaml を編集した場合の再生成漏れを検出する（PyYAML が無い環境では省略）
if python3 -c "import yaml" 2>/dev/null; then
  python3 "$MAP_ROOT/scripts/build_agents_sql.py" --check >/dev/null || die "sql/10_agents.sql が agents/*.yaml と一致しません: python3 scripts/build_agents_sql.py"
fi
run_sql "$HERE/sql/10_agents.sql"
run_sql "$HERE/sql/20_procedures.sql"
run_sql "$HERE/sql/30_grants.sql"
echo "Setup complete. Next: ./run.sh -c $CONN  （または sql/90_try.sql を Snowsight で実行）"

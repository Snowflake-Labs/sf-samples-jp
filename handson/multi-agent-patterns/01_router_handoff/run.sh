#!/usr/bin/env bash
# 01_router_handoff/run.sh - sql/90_try.sql を実行して結果を表示する（エージェントを呼ぶので数分かかる）。
# Usage: ./run.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
MAP_VERBOSE=true run_sql "$MAP_ROOT/01_router_handoff/sql/90_try.sql"

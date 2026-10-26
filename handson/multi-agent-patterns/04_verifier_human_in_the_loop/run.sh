#!/usr/bin/env bash
# 04_verifier_human_in_the_loop/run.sh - sql/90_try.sql を実行して結果を表示する（エージェントを呼ぶので数分かかる）。
# Usage: ./run.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
MAP_VERBOSE=true run_sql "$MAP_ROOT/04_verifier_human_in_the_loop/sql/90_try.sql"

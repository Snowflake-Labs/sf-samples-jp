#!/usr/bin/env bash
# 06_skill_composition/run.sh - run_patterns.py を実行（-n で回数指定、既定 3）。
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
python3 "$MAP_ROOT/06_skill_composition/run_patterns.py" -c "$CONN" -n "$RUNS"

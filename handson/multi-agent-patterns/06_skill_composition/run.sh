#!/usr/bin/env bash
# 06_skill_composition/run.sh - Run run_patterns.py; use -n to override the default three iterations.
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
python3 "$MAP_ROOT/06_skill_composition/run_patterns.py" -c "$CONN" -n "$RUNS"

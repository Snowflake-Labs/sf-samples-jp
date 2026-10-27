#!/usr/bin/env bash
# 04_verifier_human_in_the_loop/run.sh - Run sql/90_try.sql and display results; agent calls take several minutes.
# Usage: ./run.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
MAP_VERBOSE=true run_sql "$MAP_ROOT/04_verifier_human_in_the_loop/sql/90_try.sql"

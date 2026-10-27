#!/usr/bin/env bash
# 03_agent_as_tool/run.sh - Run sql/90_try.sql and display results; agent calls take several minutes.
# Usage: ./run.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
MAP_VERBOSE=true run_sql "$MAP_ROOT/03_agent_as_tool/sql/90_try.sql"

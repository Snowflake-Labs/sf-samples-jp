#!/usr/bin/env bash
# 04_verifier_human_in_the_loop/teardown.sh - Delete only this pattern's agents and procedures; keep the common foundation.
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
confirm_or_exit "04_verifier_human_in_the_loop のエージェントとプロシージャ（$DB 内）"
run_sql "$MAP_ROOT/04_verifier_human_in_the_loop/sql/99_teardown.sql"
echo "Teardown complete."

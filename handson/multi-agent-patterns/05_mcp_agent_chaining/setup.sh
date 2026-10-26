#!/usr/bin/env bash
# 05_mcp_agent_chaining/setup.sh - MCP サーバー経由でエージェントを呼ぶ構成を作成（単独で動く、再実行可能）。
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/05_mcp_agent_chaining"
preflight
run_sql "$HERE/sql/01_namespace.sql"
run_sql "$HERE/sql/02_objects.sql"
echo "Setup complete: $MCP_DB.LAB. Next: ./run.sh -c $CONN"

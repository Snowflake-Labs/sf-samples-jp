#!/usr/bin/env bash
# 05_mcp_agent_chaining/teardown.sh - パターン 05 のデータベースだけを削除（共通ウェアハウスは残す）。
# Usage: ./teardown.sh -c <connection> --confirm
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
guard_names "$MCP_DB"
confirm_or_exit "DATABASE ${MCP_DB}（エージェント 5、MCP サーバー 2、プロシージャ 1）"
run_sql "$MAP_ROOT/05_mcp_agent_chaining/sql/99_teardown.sql"
echo "Teardown complete."

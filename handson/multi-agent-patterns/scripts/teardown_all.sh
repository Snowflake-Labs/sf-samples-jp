#!/usr/bin/env bash
# teardown_all.sh - 本資材が作ったすべて（3 データベース、ウェアハウス、ロール）を削除する。
# Usage: scripts/teardown_all.sh -c <connection> --confirm
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/05_mcp_agent_chaining/teardown.sh" "$@"
"$ROOT/06_skill_composition/teardown.sh" "$@"
"$ROOT/00_common/teardown.sh" "$@"     # パターン 01-04 は共通 DB ごと削除される

#!/usr/bin/env bash
# 06_skill_composition/setup.sh - スキル / サブスキル構成を作成（単独で動く、再実行可能）。
# Usage: ./setup.sh -c <connection>
source "$(cd "$(dirname "$0")" && pwd)/../scripts/lib.sh"
map_init "$@"
HERE="$MAP_ROOT/06_skill_composition"
preflight
run_sql "$HERE/sql/01_namespace.sql"
info "Uploading skills to @$SKILL_DB.LAB.SKILL_STAGE/skills/"
while IFS= read -r f; do
  rel="${f#$HERE/skills/}"; dir="$(dirname "$rel")"
  snow stage copy -c "$CONN" "$f" "@$SKILL_DB.LAB.SKILL_STAGE/skills/$dir/" --overwrite >/dev/null 2>&1 || die "upload of $rel failed"
done < <(find "$HERE/skills" -name SKILL.md | sort)
sqlq "ALTER STAGE $SKILL_DB.LAB.SKILL_STAGE REFRESH" >/dev/null
run_sql "$HERE/sql/02_agents.sql"
echo "Setup complete: $SKILL_DB.LAB. Next: ./run.sh -c $CONN"

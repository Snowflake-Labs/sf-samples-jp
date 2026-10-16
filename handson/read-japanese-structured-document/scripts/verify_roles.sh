#!/usr/bin/env bash
# scripts/verify_roles.sh — sql/verify/roles.sql の各ケースを実行し、期待（ok / fail）と照合する。
# 1 件でも期待と違えば非 0 で終わる（setup.sh はそこで中断する）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exit_if_help "$@"
[[ -n "${CONNECTION:-}" ]] || load_deploy

n_bad=0 n_case=0 expect=""
while IFS= read -r line; do
  if [[ "$line" =~ ^--\ expect:\ (ok|fail)$ ]]; then
    expect="${BASH_REMATCH[1]}"
    continue
  fi
  [[ -z "$expect" || -z "${line// }" || "$line" == --* ]] && continue
  if sql_ok "$line"; then got=ok; else got=fail; fi
  n_case=$((n_case + 1))
  if [[ "$got" == "$expect" ]]; then
    log "  OK  expect=$expect got=$got  $(render_vars "$line")"
  else
    log "  NG  expect=$expect got=$got  $(render_vars "$line")"
    n_bad=$((n_bad + 1))
  fi
  expect=""
done <"${PROJECT_ROOT}/sql/verify/roles.sql"

((n_case > 0)) || die "検証ケースが 0 件（sql/verify/roles.sql を確認する）"
((n_bad == 0)) || die "ロール分離の検証で ${n_bad}/${n_case} 件が期待と違う"
log "ロール分離の検証：${n_case} 件すべて期待どおり"

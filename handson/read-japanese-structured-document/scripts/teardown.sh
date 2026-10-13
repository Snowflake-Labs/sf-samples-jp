#!/usr/bin/env bash
# teardown.sh — setup.sh が作ったものを Snowflake から削除する。
#
#   scripts/teardown.sh [--yes] [--keep-eval] [--no-export]
#
#   --yes        確認プロンプトを出さない
#   --keep-eval  評価 DB（正解と評価結果）と評価ロールを残す（所有権は ACCOUNTADMIN に移す）
#   --no-export  削除前の評価記録の書き出し（results/<run_id>/、件数の照合付き）を省略する
#
# 削除するのは jpdocread names が接頭辞から組み立てた名前だけ（DROP … IF EXISTS を名前で指定する）。
# SHOW の結果やワイルドカードから削除対象を組み立てない。他プロジェクトのオブジェクトには触れない。
# ローカルの data/・out/・results/・Docker イメージは消さない（消し方は README）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

YES=false KEEP_EVAL=false EXPORT=true
while (($#)); do
  case "$1" in
    --yes) YES=true; shift ;;
    --keep-eval) KEEP_EVAL=true; shift ;;
    --no-export) EXPORT=false; shift ;;
    -h|--help) print_help; exit 0 ;;
    *) die "不明なオプション: $1（--help を参照）" ;;
  esac
done

start_log teardown
require_cmd snow
load_deploy

targets=("POOL      ${COMPUTE_POOL}（動いているジョブを止めてから）" "DATABASE  ${DB}（中の Task・サービス・ステージ・表ごと）")
[[ "$KEEP_EVAL" == true ]] || targets+=("DATABASE  ${EVAL_DB}")
targets+=("WAREHOUSE ${WAREHOUSE}" "ROLE      ${ROLE_PREDICT}")
[[ "$KEEP_EVAL" == true ]] || targets+=("ROLE      ${ROLE_EVAL}")
targets+=("ROLE      ${ROLE_ADMIN}")
log "削除対象："
for t in "${targets[@]}"; do log "  $t"; done
[[ "$KEEP_EVAL" == true ]] && log "  （--keep-eval：${EVAL_DB} と ${ROLE_EVAL} は残す）"
if [[ "$EXPORT" == true ]]; then
  log "  削除の前に、評価 DB の全 run を results/<run_id>/ へ書き出して件数を照合する（--no-export で省略）"
else
  log "  --no-export：評価記録を書き出さずに削除する（書き出していない run は復元できない）"
fi
confirm "削除しますか？" || { log "中止した"; exit 0; }

# 0. 評価記録の退避。評価 DB がある場合だけ行い、件数が合わなければ何も消さずに止まる
if [[ "$EXPORT" == true ]]; then
  if [[ "$(show_count "USE ROLE ACCOUNTADMIN; SHOW DATABASES LIKE '$(like_escape "${EVAL_DB}")';")" != "0" ]]; then
    jpdocread export || die "評価記録の書き出しに失敗した、または件数が合わない（何も削除していない）。--no-export で省略できる"
  else
    log "評価 DB が無いので書き出しは省略"
  fi
fi

# 失敗しても続け、最後の残存確認で判定する（途中で止まると残りが中途半端に残る）
q() { sql_ok "USE ROLE ACCOUNTADMIN; $1" || log "  （失敗・続行）$1"; }

# 1. コンピュートプール（ジョブを止めてから）。Task・サービスは DB の削除で一緒に消える
q "ALTER COMPUTE POOL IF EXISTS ${COMPUTE_POOL} STOP ALL;"
q "DROP COMPUTE POOL IF EXISTS ${COMPUTE_POOL};"

# 2. DB（予測側。評価側は --keep-eval でなければ）
q "ALTER TASK IF EXISTS ${DB}.${SCHEMA_OPS}.T_S00 SUSPEND;"
q "DROP DATABASE IF EXISTS ${DB};"
if [[ "$KEEP_EVAL" == true ]]; then
  # ADMIN を消すと所有者がいなくなるので、評価 DB の所有権を ACCOUNTADMIN に移してから残す
  for obj in "DATABASE ${EVAL_DB}" "ALL SCHEMAS IN DATABASE ${EVAL_DB}" "ALL TABLES IN DATABASE ${EVAL_DB}" \
             "ALL VIEWS IN DATABASE ${EVAL_DB}" "ALL STAGES IN DATABASE ${EVAL_DB}"; do
    q "GRANT OWNERSHIP ON ${obj} TO ROLE ACCOUNTADMIN COPY CURRENT GRANTS;"
  done
  q "GRANT ROLE ${ROLE_EVAL} TO ROLE SYSADMIN;"
else
  q "DROP DATABASE IF EXISTS ${EVAL_DB};"
fi

# DB の削除でジョブサービスが消えるので、残っていればプールをもう一度消す
q "DROP COMPUTE POOL IF EXISTS ${COMPUTE_POOL};"

# 3. ウェアハウスとロール（下位から）
q "DROP WAREHOUSE IF EXISTS ${WAREHOUSE};"
q "DROP ROLE IF EXISTS ${ROLE_PREDICT};"
[[ "$KEEP_EVAL" == true ]] || q "DROP ROLE IF EXISTS ${ROLE_EVAL};"
q "DROP ROLE IF EXISTS ${ROLE_ADMIN};"

# 4. 残存確認（名前を指定して確かめる。LIKE の _ はエスケープして完全一致にする）
remaining=()
check() { # kind name
  local n
  n="$(show_count "USE ROLE ACCOUNTADMIN; SHOW $1 LIKE '$(like_escape "$2")';")"
  [[ "$n" == "0" ]] || remaining+=("$1 $2")
}
check DATABASES "$DB"
[[ "$KEEP_EVAL" == true ]] || check DATABASES "$EVAL_DB"
check ROLES "$ROLE_ADMIN"
check ROLES "$ROLE_PREDICT"
[[ "$KEEP_EVAL" == true ]] || check ROLES "$ROLE_EVAL"
check WAREHOUSES "$WAREHOUSE"
check "COMPUTE POOLS" "$COMPUTE_POOL"
((${#remaining[@]} == 0)) || die "残っているもの：${remaining[*]}"

# 接頭辞で始まるもの全体も数える（--keep-eval で残したもの以外は 0 のはず）
for kind in DATABASES ROLES WAREHOUSES "COMPUTE POOLS"; do
  log "  接頭辞 ${NAME_PREFIX} の ${kind}: $(show_count "USE ROLE ACCOUNTADMIN; SHOW ${kind} LIKE '$(like_escape "$NAME_PREFIX")%';") 件"
done
log "teardown 完了"

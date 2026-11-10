#!/usr/bin/env bash
# 片付け：評価記録を results/ に退避して件数を照合 → 専用オブジェクトを名前指定で消す → 残存 0 を確かめる。
#
#   scripts/teardown.sh [--yes] [--keep-eval] [--no-export]
#
# 消す名前は configs/deploy.env からだけ組み立てる（SHOW の結果やワイルドカードから作らない）。
# --keep-eval：評価結果をあとで SQL で確認するため、評価 DB・評価ロール・管理ロール・ウェアハウスを残す。保管中は費用がかかる。
# ローカルの data/・eval_data/・out/・work/・results/ は消さない。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

YES=0; KEEP=(); EXPORT=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) YES=1; shift ;;
    --keep-eval) KEEP=(--keep-eval); shift ;;
    --no-export) EXPORT=0; shift ;;
    --help|-h) sed -n 2,8p "$0"; exit 0 ;;
    *) die "未知の引数: $1（--help を見る）" ;;
  esac
done
require_cmd uv "https://docs.astral.sh/uv/ の手順で uv を入れる"
cd "$HOME_DIR"
jp() { uv run --quiet python -m jpcalc "$@"; }

if [[ "$YES" == 0 ]]; then
  jp teardown ${KEEP[@]+"${KEEP[@]}"} || true
  log "専用オブジェクトはまだ削除していない。削除するには --yes を付けて再実行する"
  exit 2
fi
if [[ "$EXPORT" == 1 ]]; then
  jp export-results --all \
    || die "評価記録の退避または件数の照合に失敗した。専用オブジェクトは削除していない。原因を修正するか、退避が不要なら --no-export を指定する"
fi
jp teardown --yes ${KEEP[@]+"${KEEP[@]}"} || die "teardown が途中で止まった。同じコマンドを再実行する（冪等）"
log "ローカルのデータは残した。消すなら: rm -rf data eval_data out work（results/ は評価記録の退避先）"

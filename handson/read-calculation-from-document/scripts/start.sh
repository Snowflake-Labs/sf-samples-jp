#!/usr/bin/env bash
# パイプラインの起動：対象の決定 → PDF の取得と照合 → 予測の入力ステージへ置く →（--eval のとき）正解を評価ステージへ
# → Task グラフ（予測ジョブ →（--eval）評価ジョブ）→ 自分の台帳だけを待って結果を表示する。
# --test はローカル検査（lint・format・設定・ガード・単体テスト。課金・DDL なし）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

usage() {
  cat <<'USAGE'
使い方:
  scripts/start.sh --corpus yakkan|contract (--docs id1,id2 | --docs-file path | --slice pilot|dev|holdout)
                   --input pdf --cards auto
                   [--eval] [--run-id id] [--resume id] [--from A|P|E] [--fail A|P:<PDF ID>]
                   [--no-cache] [--declare "要求数・見込み"] [--allow-holdout] [--no-wait] [--yes]
  scripts/start.sh --test     ローカル検査を回す（課金・DDL なし）
  scripts/start.sh --help     この説明

  --yes が無ければ、対象と見込み（PDF 数・ページ数・AI の要求数・クレジット）を表示して終了する。
  --no-cache、HOLDOUT、空のキャッシュ、pilot より多い対象では --declare が必要。
  --resume <run_id> では、成功済みの PDF を再実行しない。
  --from は --resume と一緒に指定する（A: 読み取り、P: K〜R、E: 評価のみ）。
  --eval が無ければ、正解を取得・配置・参照しない。

--test の内容（順に実行し、1 つでも落ちたら非 0 で終わる）:
  1. uv run ruff check .
  2. uv run ruff format --check .
  3. uv run python -m jpcalc check-config   設定ファイル一式の検査
  4. uv run python -m jpcalc guard          正解漏れガード（AST 検査）
  5. uv run pytest                          単体テスト・ガードのテスト（integration・network は除く）
USAGE
}

run_tests() {
  require_cmd uv "https://docs.astral.sh/uv/ の手順で uv を入れる"
  cd "$HOME_DIR"
  local steps=(
    "uv run ruff check ."
    "uv run ruff format --check ."
    "uv run python -m jpcalc check-config"
    "uv run python -m jpcalc guard"
    "uv run pytest"
  )
  for s in "${steps[@]}"; do
    log "実行: $s"
    if ! bash -c "$s"; then
      die "失敗: ${s}（上の出力を見て直し、scripts/start.sh --test を再実行する）"
    fi
  done
  log "ローカル検査はすべて通った"
}

run_pipeline() {
  local corpus="" sel=() input="" cards="" eval=0 run_args=() resume="" from="" yes=0 holdout=() rid=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --corpus) corpus="${2:?}"; shift 2 ;;
      --docs|--docs-file|--slice) sel+=("$1" "${2:?$1 の値}"); shift 2 ;;
      --input) input="${2:?}"; shift 2 ;;
      --cards) cards="${2:?}"; shift 2 ;;
      --eval) eval=1; run_args+=(--eval); shift ;;
      --run-id) [[ -z "$resume" ]] || die "--run-id と --resume は一緒に指定しない"; rid="${2:?}"; shift 2 ;;
      --declare|--fail) run_args+=("$1" "${2:?$1 の値}"); shift 2 ;;
      --resume) resume="${2:?}"; rid="$2"; run_args+=(--resume "$2"); shift 2 ;;
      --from) from="${2:?}"; run_args+=(--from "$2"); shift 2 ;;
      --no-cache|--no-wait) run_args+=("$1"); shift ;;
      --allow-holdout) holdout=(--allow-holdout); run_args+=(--allow-holdout); shift ;;
      --yes) yes=1; shift ;;
      *) usage >&2; die "未知の引数: $1" ;;
    esac
  done
  [[ "$corpus" == yakkan || "$corpus" == contract ]] || die "--corpus は yakkan か contract"
  [[ "$input" == pdf ]] || die "--input は pdf だけ（予測の入力は PDF だけにする）"
  [[ "$cards" == auto ]] || die "--cards は auto だけ（関数のカードは PDF から作る）"
  [[ ${#sel[@]} -eq 2 ]] || die "--docs・--docs-file・--slice のどれか 1 つだけを指定する"
  [[ -z "$from" || -n "$resume" ]] || die "--from は --resume <run_id> と一緒に指定する"
  [[ -z "$resume" || -z "$rid" || "$rid" == "$resume" ]] || die "--run-id と --resume は一緒に指定しない（再開は --resume だけ）"
  require_cmd uv "https://docs.astral.sh/uv/ の手順で uv を入れる"
  cd "$HOME_DIR"
  jp() { uv run --quiet python -m jpcalc "$@"; }

  local ids
  ids="$(jp targets --corpus "$corpus" "${sel[@]}" ${holdout[@]+"${holdout[@]}"})" \
    || die "対象を決められない。上のエラーを確認し、未知の ID、HOLDOUT、対象指定の重複を修正する"
  log "対象: ${ids}"
  if [[ "$yes" == 0 ]]; then
    jp run --corpus "$corpus" --pdfs "$ids" ${run_args[@]+"${run_args[@]}"} || true
    log "まだ起動していない。表示された見込みを確認し、--yes を付けて再実行する"
    exit 2
  fi
  [[ -n "$rid" ]] || rid="${corpus}-$(date -u +%Y%m%d%H%M%S)"
  [[ -n "$resume" ]] || run_args+=(--run-id "$rid")
  # 取得・PUT の前に、再開の対象と課金の宣言を確かめる（通らなければ何も置かずに止まる）
  local crc=0
  jp run --corpus "$corpus" --pdfs "$ids" --yes --check-only ${run_args[@]+"${run_args[@]}"} || crc=$?
  [[ "$crc" == 0 ]] || { log "起動の前の検査で止めた（何も置いていない）"; exit "$crc"; }
  jp fetch --corpus "$corpus" --docs "$ids" ${holdout[@]+"${holdout[@]}"} \
    || die "PDF の取得か照合に失敗した（照合値の一致を確かめる）"
  jp upload --corpus "$corpus" --pdfs "$ids" || die "予測の入力ステージに置けない（setup を先に実行する）"
  if [[ "$eval" == 1 ]]; then
    local docs
    docs="$(tr ',' '\n' <<<"$ids" | sed 's/--.*//' | sort -u | paste -sd, -)"
    jp fetch-gold --corpus "$corpus" --docs "$docs" || die "正解の取得に失敗した"
    jp upload-gold --corpus "$corpus" --pdfs "$ids" || die "正解を評価ステージに置けない（照合値の無い正解は置かない）"
  fi
  local rc=0
  jp run --corpus "$corpus" --pdfs "$ids" --yes ${run_args[@]+"${run_args[@]}"} || rc=$?
  if [[ "$eval" == 1 ]]; then
    jp evaluate --corpus "$corpus" --run-id "$rid" --report || log "評価の記録が無い（評価ジョブの失敗は台帳の S20 を見る）"
  fi
  [[ "$rc" == 0 ]] || log "失敗した。原因を修正し、scripts/start.sh ... --resume ${rid} --yes で再開する（成功済みの PDF は再実行しない）"
  return "$rc"
}

case "${1:-}" in
  --test) run_tests ;;
  --help|-h) usage ;;
  "") usage; exit 2 ;;
  *) run_pipeline "$@" ;;
esac

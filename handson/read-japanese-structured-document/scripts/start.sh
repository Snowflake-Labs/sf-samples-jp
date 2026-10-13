#!/usr/bin/env bash
# start.sh — 読み取り・Snowflake への登録・（--eval なら）評価を流す。テストの実行もここから。
#
#   scripts/start.sh --corpus yakkan|contract [--docs id,…|--docs-file path|--slice pilot|all] [--eval]
#                    [--run-id ID] [--fail Sxx:doc_id] [--yes]
#   scripts/start.sh --resume <run_id> [--from Sxx] [--fail …] [--eval]     失敗・未実行の分だけを再実行
#   scripts/start.sh --watch <run_id>                                       起動済みの run の完了を待つ
#   scripts/start.sh --test                                                 ruff・正解漏れガード・pytest（Snowflake 不要）
#   scripts/start.sh --fetch --corpus … [対象の指定] [--eval]               取得と照合だけ
#
# 実行の中身は `jpdocread run`（src/jpdocread/run.py）。対象の決定と見込みクレジットの表示 → 取得と照合 → PUT
# （同じ md5 は飛ばす）→（--eval なら正解を評価ステージへ）→ 登録 → Task グラフを起動 → 完了まで待つ。
# 失敗したら失敗したステップとジョブログの末尾、再実行のコマンドを表示して非 0 で終わる。
# --fail Sxx:doc_id は故障注入（再実行の実演用）。S20・S30・S50 は指定した文書で例外を起こす（src/jpdocread/run.py の FAIL_STEPS）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"


run_tests() {
  start_log "start-test"
  require_cmd uv
  cd "${PROJECT_ROOT}"
  echo "[test] ruff check";          uv run --quiet ruff check .
  echo "[test] ruff format --check"; uv run --quiet ruff format --check .
  echo "[test] guard";               uv run --quiet jpdocread guard
  echo "[test] pytest";              uv run --quiet pytest -q
  echo "[test] すべて通過"
}

main() {
  [[ $# -eq 0 ]] && { print_help; exit 2; }
  exit_if_help "$@"
  case "$1" in
    -h|--help) print_help ;;
    --test) shift; [[ $# -eq 0 ]] || die "--test は他のオプションと併用しない"; run_tests ;;
    --fetch)
      shift
      start_log "start-fetch"
      require_cmd uv
      jpdocread fetch "$@"
      ;;
    *)
      start_log "start"
      require_cmd uv
      # 正解漏れガード（予測コードが正解を開かないこと）
      jpdocread guard >/dev/null || die "正解漏れガードが失敗した（jpdocread guard で詳細を見る）"
      jpdocread run "$@"
      ;;
  esac
}

main "$@"

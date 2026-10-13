#!/usr/bin/env bash
# scripts/lib.sh — setup.sh / start.sh / teardown.sh の共通関数。source して使う。
#
# 接続名・オブジェクト名をここに書かない：
#   接続名  … `jpdocread connection`（環境変数 SNOWFLAKE_CONNECTION_NAME → configs/deploy.local.env。無ければ止まる）
#   名前    … `jpdocread names`（configs/deploy.env の NAME_PREFIX から組み立てる）
# SQL のテンプレート変数（<% db %> など）は、names の出力を小文字にしたキーで snow sql -D に渡す。

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_FILE:-}"

# logs/<script>-<timestamp>.log に標準出力と標準エラーを複製する
start_log() {
  local name="$1"
  mkdir -p "${LOG_DIR}"
  LOG_FILE="${LOG_DIR}/${name}-$(date +%Y%m%d-%H%M%S).log"
  export LOG_FILE
  exec > >(tee -a "${LOG_FILE}") 2>&1
  echo "[${name}] ログ: logs/$(basename "${LOG_FILE}")"
}

# 呼び出し元スクリプトの先頭のコメント（shebang の次の行から、最初のコメントでない行の手前まで）を使い方として表示する
print_help() {
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

# 引数に -h / --help があれば使い方を表示して終わる（ビルドや接続などの副作用の前に呼ぶ）
exit_if_help() {
  local arg
  for arg in "$@"; do
    case "$arg" in -h|--help) print_help; exit 0 ;; esac
  done
}

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >&2; }

die() {
  echo "エラー: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 が見つからない（README の前提を参照）"
}

# uv 経由で jpdocread を呼ぶ（依存はプロジェクトの .venv に入る）
jpdocread() {
  (cd "${PROJECT_ROOT}" && uv run --quiet jpdocread "$@")
}

# 期限切れのセッショントークンが環境変数に残っていると snow が接続名の設定より優先して失敗する（R-09）。
# 接続名で接続するときは、これらを外した環境で snow を動かす（値は表示しない）。
SNOW_UNSET_VARS=(SNOWFLAKE_TOKEN SNOWFLAKE_SESSION_TOKEN SNOWFLAKE_MASTER_TOKEN SNOWFLAKE_AUTHENTICATOR SNOWFLAKE_PASSWORD)

snow_cli() {
  local args=()
  for v in "${SNOW_UNSET_VARS[@]}"; do args+=(-u "$v"); done
  env "${args[@]}" snow "$@"
}

# 接続名と名前を読み込む。CONNECTION と、names の各キー（DB・ROLE_ADMIN など）がシェル変数になる。
load_deploy() {
  CONNECTION="$(jpdocread connection)" || die "接続名が決まらない（configs/deploy.env.example を参照）"
  local line key value
  SNOW_VARS=()
  while IFS= read -r line; do
    [[ "$line" =~ ^([A-Z0-9_]+)=([A-Za-z0-9_]+)$ ]] || die "jpdocread names の出力が想定外: $line"
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    printf -v "$key" '%s' "$value"
    SNOW_VARS+=(-D "$(tr '[:upper:]' '[:lower:]' <<<"$key")=$value")
  done < <(jpdocread names)
  [[ -n "${DB:-}" && -n "${EVAL_DB:-}" ]] || die "名前を読み込めない"
}

# SQL ファイルを実行する。失敗したら中断する（ログに詳細）。
run_sql_file() {
  local f="$1"
  log "sql: ${f#"${PROJECT_ROOT}"/}"
  if ! snow_cli sql -c "$CONNECTION" -f "$f" "${SNOW_VARS[@]}" >>"${LOG_FILE:-/dev/null}" 2>&1; then
    die "SQL の実行に失敗: ${f#"${PROJECT_ROOT}"/}（ログ: ${LOG_FILE:-なし}）"
  fi
}

# 文を実行し JSON を標準出力へ（複数文なら最後の結果）。テンプレート変数を使える
sql_json() {
  snow_cli sql -c "$CONNECTION" -q "$1" "${SNOW_VARS[@]}" --format json 2>>"${LOG_FILE:-/dev/null}"
}

# 文を実行し、成功なら 0・失敗なら非 0（出力は捨てる）
sql_ok() {
  snow_cli sql -c "$CONNECTION" -q "$1" "${SNOW_VARS[@]}" >>"${LOG_FILE:-/dev/null}" 2>&1
}

# SHOW … LIKE '<名前>' で完全一致にするため、_（1 文字のワイルドカード）を \\_ にする
like_escape() { printf '%s' "${1//_/\\\\_}"; }

# SHOW … の行数（複数文なら最後の結果）。ウェアハウスを使わない（teardown で WH を消した後にも使う）。
# 2・3 番目の引数を渡すと、その列（大小を区別しない）の値に文字列を含む行だけを数える
show_count() {
  sql_json "$1" | (cd "${PROJECT_ROOT}" && uv run --quiet python -c 'import json,sys
d=json.load(sys.stdin)
while isinstance(d,list) and d and isinstance(d[-1],list): d=d[-1]
rows=d if isinstance(d,list) else []
if len(sys.argv) > 2 and sys.argv[1]:
    col, want = sys.argv[1].lower(), sys.argv[2]
    rows=[r for r in rows if want in str({k.lower(): v for k, v in r.items()}.get(col) or "")]
print(len(rows))' "${2:-}" "${3:-}")
}

# `<% name %>` を値に置き換えた文字列（ログ表示用）
render_vars() {
  local s="$1" i kv
  for ((i = 1; i < ${#SNOW_VARS[@]}; i += 2)); do
    kv="${SNOW_VARS[$i]}"
    s="${s//<% ${kv%%=*} %>/${kv#*=}}"
  done
  printf '%s' "$s"
}

# 確認プロンプト。--yes（YES=true）なら聞かない
confirm() {
  local msg="$1" ans
  [[ "${YES:-false}" == true ]] && return 0
  read -r -p "${msg} [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]]
}

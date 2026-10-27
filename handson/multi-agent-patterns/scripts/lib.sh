#!/usr/bin/env bash
# lib.sh - 各パターンの setup / teardown が共通で使うシェル関数。
# 使い方: source "$(dirname "$0")/../scripts/lib.sh"; map_init "$@"
#
# 接続の解決順: -c <name> 引数 -> 環境変数 MAP_CONNECTION -> エラー（暗黙のデフォルト接続は使わない）。
# オブジェクト名は環境変数で上書きできる（既定値は .env.example を参照）。
set -euo pipefail

MAP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

map_init() {
  # .env はリポジトリに含めない。存在すれば読み込む。
  if [[ -f "$MAP_ROOT/.env" ]]; then set -a; source "$MAP_ROOT/.env"; set +a; fi
  CONFIRM=false
  RUNS="${MAP_RUNS:-3}"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -c|--connection) MAP_CONNECTION="${2:-}"; shift 2 ;;
      --confirm) CONFIRM=true; shift ;;
      -n|--runs) RUNS="${2:-}"; shift 2 ;;
      -h|--help) echo "Usage: $0 -c <connection> [--confirm] [-n <runs>]"; exit 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
  CONN="${MAP_CONNECTION:-}"
  [[ -n "$CONN" ]] || die "接続が指定されていません。-c <接続名> を付けるか MAP_CONNECTION を設定してください（一覧: snow connection list）"
  DB="${MAP_DATABASE:-MULTI_AGENT_PATTERNS}"
  WH="${MAP_WAREHOUSE:-MULTI_AGENT_PATTERNS_WH}"
  ROLE="${MAP_ROLE:-MULTI_AGENT_PATTERNS_ROLE}"
  MCP_DB="${MAP_MCP_DATABASE:-MAP_MCP_CHAIN}"
  SKILL_DB="${MAP_SKILL_DATABASE:-MAP_SKILL_COMPOSITION}"
  WH_SIZE="${MAP_WAREHOUSE_SIZE:-XSMALL}"
  WH_SUSPEND="${MAP_AUTO_SUSPEND:-60}"
  for name in DB WH ROLE MCP_DB SKILL_DB WH_SIZE; do
    [[ "${!name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "$name='${!name}' は英数字と _ だけの識別子にしてください"
  done
  [[ "$WH_SUSPEND" =~ ^[0-9]+$ ]] || die "MAP_AUTO_SUSPEND は秒数（整数）にしてください"
  [[ "$RUNS" =~ ^[0-9]+$ ]] || die "-n は整数にしてください"
  command -v snow >/dev/null 2>&1 || die "Snowflake CLI (snow) が見つかりません: https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation"
  VARS=(-D "db=$DB" -D "wh=$WH" -D "role=$ROLE" -D "mcp_db=$MCP_DB" -D "skill_db=$SKILL_DB"
        -D "wh_size=$WH_SIZE" -D "wh_suspend=$WH_SUSPEND")
  export MAP_CONNECTION="$CONN" MAP_DATABASE="$DB" MAP_WAREHOUSE="$WH" MAP_ROLE="$ROLE" \
         MAP_MCP_DATABASE="$MCP_DB" MAP_SKILL_DATABASE="$SKILL_DB"
}

# 1 クエリを ACCOUNTADMIN で実行し、その結果（最後の結果セット）を JSON で返す。
# 接続の既定ロールに依存しないよう、毎回 USE ROLE する（既定ロールが別のロールでも誤判定しない）。
sqlq() {
  snow sql -c "$CONN" --format json -q "USE ROLE ACCOUNTADMIN; $1" 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d[-1] if d and isinstance(d[0], list) else d))"
}

# ローカルファイルをステージにアップロードする（PUT を ACCOUNTADMIN で実行）
put_file() {  # put_file <local file> <@stage/path/>
  snow sql -c "$CONN" -q "USE ROLE ACCOUNTADMIN; PUT 'file://$1' '$2' AUTO_COMPRESS = FALSE OVERWRITE = TRUE" >/dev/null 2>&1
}
jfield() { python3 -c "import json,sys; d=json.loads(sys.argv[1]); print($2)" "$1"; }

# SQL ファイルを <% var %> テンプレート変数つきで実行する。失敗時は末尾ログを表示して終了。
run_sql() {
  local file="$1" log
  info "Running ${file#$MAP_ROOT/}"
  if ! log="$(snow sql -c "$CONN" -f "$file" "${VARS[@]}" 2>&1)"; then
    echo "$log" | tail -25 >&2
    die "$file failed"
  fi
  [[ "${MAP_VERBOSE:-false}" == "true" ]] && echo "$log"
  return 0
}

# 前提チェック: 接続、ACCOUNTADMIN、クロスリージョン推論。アカウント設定の変更はオプトインのみ。
preflight() {
  info "Checking connection"
  snow connection test -c "$CONN" >/dev/null 2>&1 || { sleep 5; snow connection test -c "$CONN" >/dev/null 2>&1; } \
    || die "接続テストに失敗しました（snow connection test -c <接続名>）"
  local ctx xr value
  ctx="$(sqlq "SELECT CURRENT_ROLE() AS R")" || die "ACCOUNTADMIN ロールを使える接続が必要です（USE ROLE ACCOUNTADMIN に失敗）"
  [[ "$(jfield "$ctx" "d[0]['R']")" == "ACCOUNTADMIN" ]] || die "ACCOUNTADMIN ロールを使える接続が必要です"
  xr="$(sqlq "SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT")"
  value="$(jfield "$xr" "d[0]['value'] if d else 'DISABLED'")"
  if [[ "$value" == "DISABLED" ]]; then
    if [[ "${MAP_ENABLE_CROSS_REGION:-false}" == "true" ]]; then
      info "Enabling cross-region inference (MAP_ENABLE_CROSS_REGION=true)"
      sqlq "ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION'" >/dev/null
    else
      echo "WARNING: CORTEX_ENABLED_CROSS_REGION が DISABLED です。モデルがリージョンにない場合エージェントが失敗します。"
      echo "         MAP_ENABLE_CROSS_REGION=true で再実行すると有効化します（アカウントレベルの変更）。"
    fi
  else
    info "Cross-region inference: $value"
  fi
}

# 共通基盤（00_common）がデプロイ済みかを確認する
require_common() {
  local out
  # 一時的な接続エラーで「未作成」と誤判定しないよう 1 回だけ再試行する
  out="$(sqlq "SHOW PROCEDURES LIKE 'BUILD_CONTROLLER_ZIP' IN SCHEMA $DB.AGENTS")" \
    || { sleep 5; out="$(sqlq "SHOW PROCEDURES LIKE 'BUILD_CONTROLLER_ZIP' IN SCHEMA $DB.AGENTS")"; } || out="[]"
  [[ "$(jfield "$out" "len(d)")" != "0" ]] || die "先に 00_common/setup.sh を実行してください（$DB.AGENTS が見つかりません）"
}

# 指定エージェントが存在するかを確認する
require_agents() {
  local out name
  out="$(sqlq "SHOW AGENTS IN SCHEMA $DB.AGENTS")" || { sleep 5; out="$(sqlq "SHOW AGENTS IN SCHEMA $DB.AGENTS")"; } || out="[]"
  for name in "$@"; do
    jfield "$out" "'$name' in [r['name'] for r in d]" | grep -q True || die "$name がありません。依存するパターンを先に setup してください"
  done
}

# teardown の確認。--confirm が無ければ何もしないで終了。
confirm_or_exit() {
  echo "次を削除します:"; printf '  %s\n' "$@"
  $CONFIRM || { echo "何も削除していません。--confirm を付けて再実行してください。"; exit 1; }
}

# システムロール・既定オブジェクトは削除しない
guard_names() {
  local x
  for x in "$@"; do
    case "$(tr '[:lower:]' '[:upper:]' <<<"$x")" in
      SNOWFLAKE|SNOWFLAKE_SAMPLE_DATA|ACCOUNTADMIN|SYSADMIN|SECURITYADMIN|USERADMIN|ORGADMIN|PUBLIC|COMPUTE_WH)
        die "$x は削除できない名前です" ;;
    esac
  done
}

# コントローラ（controller/src/*.py）をステージに置き、Snowflake 内で zip を作り直す（00_common / 07 / 08 が使う）
deploy_controller() {
  info "Uploading controller/src/*.py to @${DB}.AGENTS.APP_STAGE/lib/src"
  find "$MAP_ROOT/controller" -name "__pycache__" -type d -prune -exec rm -rf {} +
  local f
  for f in "$MAP_ROOT"/controller/src/*.py; do
    put_file "$f" "@${DB}.AGENTS.APP_STAGE/lib/src/" || die "upload of $f failed"
  done
  sqlq "CALL ${DB}.AGENTS.BUILD_CONTROLLER_ZIP()" >/dev/null || die "BUILD_CONTROLLER_ZIP failed"
}

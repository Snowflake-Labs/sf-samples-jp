#!/usr/bin/env bash
# setup.sh — Snowflake にオブジェクトを作る。何度実行しても同じ状態になる。
#
#   scripts/setup.sh [--corpus yakkan|contract|all] [--skip-build] [--skip-fetch] [--yes]
#
#   1. 前提確認（uv・snow・接続・docker）と依存の導入
#   2. データ取得と manifest の照合（--corpus のコーパスの pilot。既定は両コーパス。不一致なら DDL の前に止まる）と正解漏れガード
#   3. DDL：ロール → オブジェクト → 権限（sql/setup/）
#   4. ロール分離の検証（scripts/verify_roles.sh。USE SECONDARY ROLES NONE 付き）
#   5. ジョブイメージのビルドと push（--skip-build で省略。前回のタグを使う）
#   6. ジョブ仕様・図 few-shot・プロシージャ・Task グラフ（ルートは SUSPENDED のまま）・ビュー
#   7. 作成物の一覧
#
#   --corpus      few-shot を用意するコーパス（既定 all）
#   --skip-build  イメージをビルドしない（configs/deploy.local.env の IMAGE_TAG を使う）
#   --skip-fetch  データの取得と照合を省略する（取得済みで、照合も済んでいるときだけ）
#   --yes         確認を出さない（このスクリプトは何も削除しないので、確認は作成対象の表示だけ）
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

CORPORA=(yakkan contract) SKIP_BUILD=false SKIP_FETCH=false YES=false
while (($#)); do
  case "$1" in
    --corpus)
      [[ $# -ge 2 ]] || die "--corpus に値が要る"
      case "$2" in yakkan|contract) CORPORA=("$2") ;; all) CORPORA=(yakkan contract) ;; *) die "--corpus は yakkan|contract|all";; esac
      shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --skip-fetch) SKIP_FETCH=true; shift ;;
    --yes) YES=true; shift ;;
    -h|--help) print_help; exit 0 ;;
    *) die "不明なオプション: $1（--help を参照）" ;;
  esac
done

start_log setup

# ---------------------------------------------------------------- 1. 前提
for c in uv snow; do require_cmd "$c"; done
(cd "${PROJECT_ROOT}" && uv sync --quiet) || die "uv sync に失敗"
load_deploy
log "接続は解決済み（名前は表示しない）。オブジェクト名の接頭辞：${NAME_PREFIX}"
sql_ok "SELECT 1" || die "Snowflake に接続できない（snow connection test -c <接続名> で確かめる。期限切れのトークン環境変数は外して実行している）"
if [[ "$SKIP_BUILD" != true ]]; then
  require_cmd docker
  docker info >/dev/null 2>&1 || die "Docker デーモンが動いていない（Docker Desktop を起動するか --skip-build）"
fi

# ---------------------------------------------------------------- 2. データの照合（DDL の前）
if [[ "$SKIP_FETCH" == true ]]; then
  log "データの取得と照合を省略（--skip-fetch）"
else
  for corpus in "${CORPORA[@]}"; do
    log "データの取得と照合：${corpus}（pilot。不一致なら何も作らずに止まる）"
    jpdocread fetch --corpus "$corpus" || die "${corpus} のデータが manifest と一致しない・取得できない（Hugging Face に接続できるか確かめる。何も作っていない）"
  done
fi
jpdocread guard >/dev/null || die "正解漏れガードが失敗した（何も作っていない）"

# ---------------------------------------------------------------- 3. DDL
log "作成するもの（すべて接頭辞 ${NAME_PREFIX}）：DB ${DB}・${EVAL_DB}、ロール ${ROLE_ADMIN}・${ROLE_PREDICT}・${ROLE_EVAL}、WH ${WAREHOUSE}、プール ${COMPUTE_POOL}"
confirm "作成しますか？" || { log "中止した"; exit 0; }
run_sql_file "${PROJECT_ROOT}/sql/setup/00_roles.sql"
run_sql_file "${PROJECT_ROOT}/sql/setup/01_objects.sql"
run_sql_file "${PROJECT_ROOT}/sql/setup/02_grants.sql"

# ---------------------------------------------------------------- 4. ロール分離
log "ロール分離の検証"
bash "${PROJECT_ROOT}/scripts/verify_roles.sh"

# ---------------------------------------------------------------- 5. イメージ
if [[ "$SKIP_BUILD" == true ]]; then
  IMAGE_TAG="$(cd "${PROJECT_ROOT}" && uv run --quiet python -c "from jpdocread.common.local_settings import lookup_local; print(lookup_local('IMAGE_TAG') or '')")"
  [[ -n "$IMAGE_TAG" ]] || die "--skip-build だが configs/deploy.local.env に IMAGE_TAG が無い（一度ビルドする）"
  # teardown でイメージリポジトリごと消えるので、タグがリポジトリにあることを確かめる（無いと S30 で初めて失敗する）
  n_img="$(show_count "USE ROLE ${ROLE_ADMIN}; SHOW IMAGES LIKE '$(like_escape "${IMAGE_NAME}")' IN IMAGE REPOSITORY ${DB}.${SCHEMA_APP}.IMAGES;" \
           "tags" "${IMAGE_TAG}")"
  [[ "$n_img" != "0" ]] \
    || die "イメージ ${IMAGE_NAME}:${IMAGE_TAG} がリポジトリに無い（teardown の後は --skip-build を外してビルドし直す）"
  log "ビルドを省略（IMAGE_TAG=${IMAGE_TAG}。リポジトリにあることを確認）"
else
  bash "${PROJECT_ROOT}/scripts/build_push.sh"
fi

# ---------------------------------------------------------------- 6. ジョブ仕様・図 few-shot・プロシージャ
jpdocread deploy specs || die "ジョブ仕様を置けない"
for corpus in "${CORPORA[@]}"; do
  # 供出元の正解から few-shot を作る（正解は採点側の準備にだけ使い、予測経路には入れない）
  jpdocread deploy prompt --corpus "$corpus" || die "${corpus} の図 few-shot を用意できない"
done
for f in procedures/steps procedures/s20_parse_text procedures/s40_figures procedures/s55_register \
         procedures/s60_evaluate tasks/dag views/output_views views/eval_views; do
  run_sql_file "${PROJECT_ROOT}/sql/${f}.sql"
done


# ---------------------------------------------------------------- 7. 一覧
log "作成物："
for kind in "DATABASES" "ROLES" "WAREHOUSES" "COMPUTE POOLS"; do
  n="$(show_count "USE ROLE ACCOUNTADMIN; SHOW ${kind} LIKE '$(like_escape "${NAME_PREFIX}")%';")"
  log "  ${kind}: ${n} 件"
done
log "setup 完了"

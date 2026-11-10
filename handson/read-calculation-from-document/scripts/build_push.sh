#!/usr/bin/env bash
# ジョブのイメージをローカルでビルドし（linux/amd64）、イメージリポジトリへ push する。
#
#   scripts/build_push.sh [--build-only] [<tag>]
#
# タグは UTC の日時 14 桁（latest は使わない）。push したタグを configs/deploy.local.env の IMAGE_TAG に書く
# （接続名などほかのキーは書き換えない）。--build-only はビルドとイメージ内の検査だけ（Snowflake に接続しない）。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

BUILD_ONLY=0
if [[ "${1:-}" == "--help" ]]; then sed -n 2,7p "$0"; exit 0; fi
if [[ "${1:-}" == "--build-only" ]]; then BUILD_ONLY=1; shift; fi
TAG="${1:-$(date -u '+%Y%m%d%H%M%S')}"
[[ "$TAG" =~ ^[0-9]{14}$ ]] || die "タグは UTC の日時 14 桁にする（latest は使わない）: ${TAG}"

require_cmd uv "https://docs.astral.sh/uv/ の手順で uv を入れる"
require_cmd docker "Docker と buildx を入れる"
cd "$HOME_DIR"
NAME="$(uv run --quiet python -c 'from jpcalc.ops import deploy_values; print(deploy_values()["image_name"])')"
LOCAL="${NAME}:${TAG}"

# 依存を uv.lock から固定する（ローカルのテストと同じ版。git 管理外の生成物）
uv export --frozen --no-dev --no-hashes --no-emit-project --quiet -o container/requirements.lock \
  || die "uv export に失敗した"

log "docker build ${LOCAL}（linux/amd64）"
docker buildx build --platform linux/amd64 -f container/Dockerfile -t "$LOCAL" --load . \
  || die "docker build に失敗した"
# イメージの中で正解漏れガードを回し、データ・設定・資格情報が入っていないことを確かめる
docker run --rm --platform linux/amd64 "$LOCAL" guard || die "イメージの中の正解漏れガードが失敗した"
docker run --rm --platform linux/amd64 --entrypoint sh "$LOCAL" -c \
  'test "$(id -u)" = 1000 && ! test -e /app/configs/deploy.local.env && ! test -e /app/configs/shots && ! test -e /app/configs/opt && ! ls /app/configs/opt_*.yaml >/dev/null 2>&1 && ! ls /app/configs/prompts/k_cards_contract_p*.txt >/dev/null 2>&1 && ! test -e /app/data && ! test -e /app/eval_data && ! test -e /app/work && ! test -e /app/out && ! test -e /app/docs && test "$(ls /app/*.md)" = /app/README.md' \
  || die "イメージに入れてはならないものがある（または root で動く）"
log "イメージの検査が通った"
[[ "$BUILD_ONLY" == 1 ]] && exit 0

REPO="$(uv run --quiet python -m jpcalc image-repo)" || die "イメージリポジトリの URL を取れない（setup を先に実行する）"
CONN="$(uv run --quiet python -c 'from jpcalc.common.local_settings import resolve_connection_name as r; print(r())')"
log "push → <repository>/${NAME}:${TAG}"
snow spcs image-registry login -c "$CONN" >/dev/null || die "イメージレジストリにログインできない"
docker tag "$LOCAL" "${REPO}/${NAME}:${TAG}"
# 作ったばかりのリポジトリでは応答待ちで切れることがある。同じタグで 3 回まで試す（層は上書きされない）
ok=0
for i in 1 2 3; do
  if docker push "${REPO}/${NAME}:${TAG}" >/dev/null; then ok=1; break; fi
  log "push に失敗した（${i}/3）。30 秒後に試し直す"; sleep 30
done
[[ "$ok" == 1 ]] || die "docker push に 3 回失敗した（ネットワークと snow のログインを確認し、scripts/setup.sh --corpus yakkan --yes を再実行する。build_push.sh だけでは手本が作られない）"
uv run --quiet python -m jpcalc image-repo --record-tag "$TAG" || die "push したタグを確かめられない"
log "IMAGE_TAG=${TAG} を configs/deploy.local.env に書いた"

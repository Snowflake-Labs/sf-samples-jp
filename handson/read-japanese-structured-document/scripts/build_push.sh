#!/usr/bin/env bash
# scripts/build_push.sh — ジョブイメージをローカルでビルドし（linux/amd64）、イメージリポジトリへ push する。
#
#   scripts/build_push.sh [<tag>]
#
# タグは UTC の日時（latest を使わない）。push したタグを configs/deploy.local.env の IMAGE_TAG に書く
# （ほかのキー＝接続名・データの場所は書き換えない）。push 後に SHOW IMAGES でタグを確かめる。
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
exit_if_help "$@"
[[ -n "${CONNECTION:-}" ]] || load_deploy
require_cmd docker

TAG="${1:-$(date -u '+%Y%m%d%H%M%S')}"
[[ "$TAG" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$TAG" != latest ]] || die "タグの形が不正（latest は使わない）: $TAG"
LOCAL_IMAGE="${IMAGE_NAME}:${TAG}"

# 依存を uv.lock から固定する（ローカルのテストと同じ版。git 管理外の生成物）
(cd "${PROJECT_ROOT}" && uv export --frozen --no-dev --no-hashes --no-emit-project --quiet \
  -o container/requirements.lock) || die "uv export に失敗"

log "docker build ${LOCAL_IMAGE}（linux/amd64）"
docker buildx build --platform linux/amd64 -f "${PROJECT_ROOT}/container/Dockerfile" -t "${LOCAL_IMAGE}" \
  --load "${PROJECT_ROOT}" >>"${LOG_FILE:-/dev/null}" 2>&1 || die "docker build に失敗（ログ: ${LOG_FILE:-なし}）"
docker run --rm --platform linux/amd64 "${LOCAL_IMAGE}" guard >>"${LOG_FILE:-/dev/null}" 2>&1 \
  || die "イメージ内の正解漏れガードが失敗した"

REPO_URL="$(sql_json "USE ROLE ${ROLE_ADMIN}; SHOW IMAGE REPOSITORIES IN SCHEMA ${DB}.${SCHEMA_APP};" \
  | (cd "${PROJECT_ROOT}" && uv run --quiet python -c '
import json,sys
d=json.load(sys.stdin)
while isinstance(d,list) and d and isinstance(d[-1],list): d=d[-1]
print(next(r["repository_url"] for r in d if r["name"]=="IMAGES"))'))" || die "イメージリポジトリが無い（setup の DDL を先に）"

log "push → <repository>/${IMAGE_NAME}:${TAG}"
snow_cli spcs image-registry login -c "$CONNECTION" >>"${LOG_FILE:-/dev/null}" 2>&1 \
  || die "イメージレジストリにログインできない"
docker tag "${LOCAL_IMAGE}" "${REPO_URL}/${IMAGE_NAME}:${TAG}"
docker push "${REPO_URL}/${IMAGE_NAME}:${TAG}" >>"${LOG_FILE:-/dev/null}" 2>&1 || die "docker push に失敗"

n="$(show_count "USE ROLE ${ROLE_ADMIN}; SHOW IMAGES IN IMAGE REPOSITORY ${DB}.${SCHEMA_APP}.IMAGES;")"
sql_json "USE ROLE ${ROLE_ADMIN}; SHOW IMAGES IN IMAGE REPOSITORY ${DB}.${SCHEMA_APP}.IMAGES;" | grep -q "\"${TAG}\"" \
  || die "push したタグ ${TAG} が SHOW IMAGES に無い"

(cd "${PROJECT_ROOT}" && uv run --quiet python - "$TAG" <<'PY') || die "deploy.local.env に IMAGE_TAG を書けない"
import re, sys
from pathlib import Path
p = Path("configs/deploy.local.env")
text = p.read_text(encoding="utf-8") if p.exists() else ""
line = f"IMAGE_TAG={sys.argv[1]}"
new = re.sub(r"(?m)^IMAGE_TAG=.*$", line, text) if re.search(r"(?m)^IMAGE_TAG=", text) else text.rstrip("\n") + ("\n" if text else "") + line + "\n"
p.write_text(new, encoding="utf-8")
PY
log "IMAGE_TAG=${TAG} を configs/deploy.local.env に書いた（イメージ ${n} 件）"

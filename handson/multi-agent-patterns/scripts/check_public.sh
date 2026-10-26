#!/usr/bin/env bash
# check_public.sh - 公開前チェック。コミット前に実行し、0 件であることを確認する。
#   1. MAP_DENYLIST（.env、| 区切り）に書いた開発環境の識別子が、公開対象ファイルに含まれていないか
#   2. ホスト名・秘密鍵・パスワードらしき文字列
#   3. 公開してはいけないファイル（.env, results/, __pycache__/, *.zip）が git に追加されていないか
#   4. 10MB を超えるファイル
#   5. 静的テスト（tests/）: 命名規約（snow を含む名前の禁止）、テンプレート、構成
# Usage: scripts/check_public.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
fail=0
report() { echo "NG: $*"; fail=1; }

# 公開対象 = git が追跡する or 追跡しうるファイル（.gitignore で除外されたものを除く）
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(git ls-files --cached --others --exclude-standard -- . | sort -u)  # bash 3.2 互換
[[ ${#FILES[@]} -gt 0 ]] || { echo "公開対象ファイルが見つかりません"; exit 1; }

if [[ -n "${MAP_DENYLIST:-}" ]]; then
  if grep -I -n -i -E "$MAP_DENYLIST" -- "${FILES[@]}" >/dev/null 2>&1; then
    report "MAP_DENYLIST に一致する文字列があります（ファイル名のみ表示）:"
    grep -I -l -i -E "$MAP_DENYLIST" -- "${FILES[@]}" | sed 's/^/    /'
  fi
else
  echo "WARNING: MAP_DENYLIST が未設定です（.env に開発アカウント・ユーザー・接続名を | 区切りで設定してください）"
fi

if grep -I -n -E "[A-Za-z0-9-]+\.snowflakecomputing\.com|BEGIN (RSA |ENCRYPTED )?PRIVATE KEY|(password|passwd|token|secret)\s*[:=]\s*['\"][^<'\"]{6,}" -- "${FILES[@]}" >/dev/null 2>&1; then
  report "ホスト名・秘密情報らしき文字列があります:"
  grep -I -l -E "[A-Za-z0-9-]+\.snowflakecomputing\.com|BEGIN (RSA |ENCRYPTED )?PRIVATE KEY|(password|passwd|token|secret)\s*[:=]\s*['\"][^<'\"]{6,}" -- "${FILES[@]}" | sed 's/^/    /'
fi

for f in "${FILES[@]}"; do
  case "$f" in
    .env|*/.env|*results/*|*__pycache__*|*.zip|*.pyc) report "公開してはいけないファイル: $f" ;;
  esac
  [[ -f "$f" ]] && (( $(wc -c <"$f") > 10485760 )) && report "10MB を超えるファイル: $f"
done

if python3 -c "import pytest, yaml, jsonschema" 2>/dev/null; then
  python3 -m pytest tests -q >/tmp/map_check_pytest.log 2>&1 || { report "静的テストが失敗しました（/tmp/map_check_pytest.log）"; tail -15 /tmp/map_check_pytest.log; }
else
  echo "WARNING: pytest / pyyaml / jsonschema が無いため静的テストを省略しました（pip install -r tests/requirements.txt）"
fi

if [[ $fail -eq 0 ]]; then echo "OK: 公開前チェックをすべて通過しました（${#FILES[@]} files）"; fi
exit $fail

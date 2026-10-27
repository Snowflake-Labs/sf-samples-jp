#!/usr/bin/env bash
# check_public.sh - Pre-publication checks. Run before committing and require zero findings.
#   1. Development identifiers from the pipe-separated MAP_DENYLIST in .env
#   2. Hostnames, private keys, and password-like strings
#   3. Files that must not be tracked: .env, results/, __pycache__/, and *.zip
#   4. Files larger than 10 MB
#   5. Static tests for naming rules, templates, and repository structure
# Usage: scripts/check_public.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
fail=0
report() { echo "NG: $*"; fail=1; }

# Public files are tracked or trackable files, excluding anything ignored by Git.
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(git ls-files --cached --others --exclude-standard -- . | sort -u)  # Bash 3.2 compatible.
[[ ${#FILES[@]} -gt 0 ]] || { echo "公開対象ファイルが見つかりません"; exit 1; }

if [[ -n "${MAP_DENYLIST:-}" ]]; then
  AUTHOR="sfc-gh-""yshi""bui"
  DENY_HITS=""
  while IFS= read -r hit; do
    file="${hit%%:*}"
    rest="${hit#*:}"
    content="${rest#*:}"
    [[ "$file" == "README.md" && "$content" == "- 作成者: [$AUTHOR](https://github.com/$AUTHOR)" ]] && continue
    [[ "$file" == "README.en.md" && "$content" == "- Author: [$AUTHOR](https://github.com/$AUTHOR)" ]] && continue
    DENY_HITS="${DENY_HITS}${file}"$'\n'
  done < <(grep -I -n -i -E "$MAP_DENYLIST" -- "${FILES[@]}" 2>/dev/null || true)
  if [[ -n "$DENY_HITS" ]]; then
    report "MAP_DENYLIST に一致する文字列があります（ファイル名のみ表示）:"
    printf '%s' "$DENY_HITS" | sort -u | sed '/^$/d; s/^/    /'
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

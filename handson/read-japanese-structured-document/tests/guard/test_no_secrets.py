"""秘密情報・接続情報の検査。

git の管理対象になり得るファイル（追跡済み＋無視されていない未追跡）を対象に、
1. 鍵・トークン・アカウント URL の形をした文字列が無い
2. 実行時に分かる禁止文字列（ローカルで解決した接続名と、環境変数 JA_DOC_STRUCTURED_FORBIDDEN_STRINGS）が無い
を確かめる。2 の値そのものはリポジトリに書けないので、実行時に読む。
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path

import pytest
from fixtures.repo_files import publishable_files

from jpdocread.common.local_settings import LocalSettingError, resolve_connection_name
from jpdocread.common.paths import HOME

FORBIDDEN_ENV = "JA_DOC_STRUCTURED_FORBIDDEN_STRINGS"

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "account_url": re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.snowflakecomputing\.com", re.I),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "hf_token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "password_assignment": re.compile(
        r"(?i)\b(password|passwd|secret)\s*[:=]\s*['\"][^'\"<>]{4,}['\"]"
    ),
}


def find_patterns(text: str) -> list[str]:
    return [name for name, rx in PATTERNS.items() if rx.search(text)]


def runtime_forbidden() -> list[str]:
    values = [v.strip() for v in os.environ.get(FORBIDDEN_ENV, "").split(",") if v.strip()]
    with contextlib.suppress(LocalSettingError):  # 接続名が未設定なら、環境変数の分だけで検査する
        values.append(resolve_connection_name())
    return values


FILES = [p for p in publishable_files() if p.resolve() != Path(__file__).resolve()]


def test_scans_some_files():
    assert any(p.name == "pyproject.toml" for p in FILES)


def test_ignored_files_are_not_scanned():
    names = {str(p.relative_to(HOME)) for p in FILES}
    assert "TASK.md" not in names
    assert not any(n.startswith(("data/", ".venv/", "logs/")) for n in names)


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(HOME)))
def test_no_secret_patterns(path):
    assert find_patterns(path.read_text(encoding="utf-8", errors="ignore")) == []


def test_no_runtime_forbidden_strings():
    forbidden = runtime_forbidden()
    if not forbidden:
        pytest.skip(f"禁止文字列が得られない（接続名が未設定で、{FORBIDDEN_ENV} も無い）")
    hits = {
        str(p.relative_to(HOME)): [
            s
            for s in forbidden
            if s.lower() in p.read_text(encoding="utf-8", errors="ignore").lower()
        ]
        for p in FILES
    }
    assert {k: v for k, v in hits.items() if v} == {}


class TestDetectors:
    def test_detects_private_key(self):
        assert find_patterns("-----BEGIN ENCRYPTED PRIVATE KEY-----") == ["private_key"]

    def test_detects_account_url(self):
        assert "account_url" in find_patterns("https://myorg-myacct.snowflakecomputing.com")

    def test_detects_password_literal(self):
        assert "password_assignment" in find_patterns('password = "hunter22"')

    def test_placeholder_is_fine(self):
        assert find_patterns("password=<your_password>\nCONNECTION_NAME=<your_connection>") == []

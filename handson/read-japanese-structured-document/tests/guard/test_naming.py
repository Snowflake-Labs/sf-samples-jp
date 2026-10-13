"""命名規則の検査。

1. configs/ と sql/ に、自前の名前として snow / snowflake を含む語が無い（Snowflake 提供の名前は例外）
2. sql/ で作る DB・スキーマ・ロール・WH・プールの名前が、接頭辞かテンプレート変数で始まる
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fixtures.repo_files import publishable_files

from jpdocread.common.names import load_names
from jpdocread.common.paths import CONFIGS, HOME

SQL_DIR = HOME / "sql"

# Snowflake が提供する名前（自前の名前ではないので許す）。大文字小文字を区別して部分一致で許す
ALLOWED_PROVIDED = (
    "SNOWFLAKE.CORTEX",
    "SNOWFLAKE.CORE",
    "SNOWFLAKE.ACCOUNT_USAGE",
    "SNOWFLAKE_SSE",
    "SNOWFLAKE_CONNECTION_NAME",
    "snowflake-connector-python",
    "/snowflake/session/token",
)
# 文章中の製品名（完全一致のときだけ許す。Snowflake_DB のような名前は許さない）
ALLOWED_WORDS = ("Snowflake",)
WORD_RE = re.compile(r"[A-Za-z0-9_./-]*snow[A-Za-z0-9_./-]*", re.IGNORECASE)
# 行頭（空白のみ前置）の CREATE だけを見る。`GRANT CREATE DATABASE ON ACCOUNT` は権限であって作成ではない
CREATE_RE = re.compile(
    r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(DATABASE|SCHEMA|ROLE|WAREHOUSE|COMPUTE\s+POOL)"
    r"\s+(?:IF\s+NOT\s+EXISTS\s+)?(<%\s*\w+\s*%>[^\s;(]*|[^\s;(]+)",
    re.IGNORECASE | re.MULTILINE,
)
TEMPLATE_RE = re.compile(r"^(?:<%\s*\w+\s*%>|&\{?\w+\}?|\$\{?\w+\}?|IDENTIFIER\()")


def banned_words(text: str) -> list[str]:
    hits = []
    for m in WORD_RE.finditer(text):
        word = m.group(0)
        if word in ALLOWED_WORDS or any(a in word for a in ALLOWED_PROVIDED):
            continue
        hits.append(word)
    return hits


def bad_create_names(sql: str, prefix: str) -> list[str]:
    bad = []
    for kind, name in CREATE_RE.findall(sql):
        short = name.strip('"').split(".")[-1]
        if not (short.startswith(prefix) or TEMPLATE_RE.match(name)):
            bad.append(f"{kind} {name}")
    return bad


def _files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """root 配下で patterns に合う、公開され得るファイル（.gitignore の対象は除く）。"""
    return [
        p
        for p in publishable_files()
        if p.is_relative_to(root) and any(p.match(pat) for pat in patterns)
    ]


@pytest.mark.parametrize(
    "path",
    _files(CONFIGS, ("*.yaml", "*.env", "*.example", "*.txt")) + _files(SQL_DIR, ("*.sql",)),
    ids=lambda p: str(p.relative_to(HOME)),
)
def test_no_banned_word_in_own_names(path):
    assert banned_words(path.read_text(encoding="utf-8")) == []


def test_sql_creates_only_prefixed_objects():
    prefix = load_names().prefix
    bad = {
        str(p.relative_to(HOME)): bad_create_names(p.read_text(encoding="utf-8"), prefix)
        for p in _files(SQL_DIR, ("*.sql",))
    }
    assert {k: v for k, v in bad.items() if v} == {}


class TestDetectors:
    """検査そのものが違反を検出できること（逆対照）。"""

    def test_detects_banned_word(self):
        assert banned_words("CREATE TABLE my_snow_table") == ["my_snow_table"]

    @pytest.mark.parametrize(
        "name", ["SNOWFLAKE_DB", "Snowflake_Corp", "snow_user", "MY_SNOWFLAKE_SCHEMA"]
    )
    def test_detects_names_from_parent_rules(self, name):
        # 名前に snow・snowflake を含めない規則の禁止例
        assert banned_words(f"x = {name}") == [name]

    def test_allows_provided_names(self):
        assert (
            banned_words(
                "GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER; ENCRYPTION=(TYPE='SNOWFLAKE_SSE')"
            )
            == []
        )

    def test_detects_unprefixed_create(self):
        sql = "CREATE DATABASE IF NOT EXISTS OTHER_DB;\nCREATE OR REPLACE ROLE P_ADMIN;"
        assert bad_create_names(sql, "P_") == ["DATABASE OTHER_DB"]

    def test_grant_create_privilege_is_not_a_create(self):
        sql = "GRANT CREATE COMPUTE POOL ON ACCOUNT TO ROLE P_ADMIN;\nGRANT CREATE DATABASE ON ACCOUNT TO ROLE X;"
        assert bad_create_names(sql, "P_") == []

    def test_allows_template_and_qualified_names(self):
        sql = "CREATE SCHEMA IF NOT EXISTS <% db %>.P_RAW;\nCREATE SCHEMA P_DB.P_OPS;"
        assert bad_create_names(sql, "P_") == []

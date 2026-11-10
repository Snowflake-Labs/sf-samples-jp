"""命名ガード：自前のオブジェクト名・識別子に snow / snowflake を含めない。

公式の製品名・関数名・CLI 名・依存パッケージ名（例：snowflake-connector-python）は説明上必要なので、
検査は「自前の名前を定義する場所」に絞る：
- configs/deploy.env の値と、そこから組み立てた全オブジェクト名
- src/ と tests/ の Python で定義する関数・クラス・変数・引数の名前
- configs/*.yaml のキー
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from jpcalc.common.envfile import read_env_file
from jpcalc.common.names import BANNED_WORD_RE, load_names
from jpcalc.common.paths import CONFIGS, DEPLOY_ENV, HOME

PY_FILES = sorted((HOME / "src").rglob("*.py")) + sorted((HOME / "tests").rglob("*.py"))


def defined_names(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out.append((node.lineno, node.name))
        elif isinstance(node, ast.arg):
            out.append((node.lineno, node.arg))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            out.append((node.lineno, node.id))
    return out


def banned_in_code(code: str) -> list[str]:
    return [f"{ln}:{n}" for ln, n in defined_names(ast.parse(code)) if BANNED_WORD_RE.search(n)]


def test_deploy_env_values():
    assert not [v for v in read_env_file(DEPLOY_ENV).values() if BANNED_WORD_RE.search(v)]
    assert not [v for v in load_names().account_objects().values() if BANNED_WORD_RE.search(v)]


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(HOME)))
def test_python_defined_names(path: Path):
    assert banned_in_code(path.read_text(encoding="utf-8")) == []


def _keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{prefix}{k}"
            yield from _keys(v, f"{prefix}{k}.")
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v, prefix)


@pytest.mark.parametrize(
    "path", sorted(CONFIGS.rglob("*.yaml")), ids=lambda p: str(p.relative_to(HOME))
)
def test_yaml_keys(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [k for k in _keys(data) if BANNED_WORD_RE.search(k)] == []


class TestDetector:
    def test_catches_bad_names(self):
        code = "snow_user = 1\ndef load_snowflake_db(): pass\nclass SnowThing: pass\n"
        assert sorted(banned_in_code(code)) == ["1:snow_user", "2:load_snowflake_db", "3:SnowThing"]

    def test_official_import_is_not_a_definition(self):
        assert (
            banned_in_code("import snowflake.connector\nconn = snowflake.connector.connect\n") == []
        )

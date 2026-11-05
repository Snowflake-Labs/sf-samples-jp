"""SQL のひな型（<% 名前 %>）に値を差し込み、文に分ける。

値は configs/deploy.env の接頭辞から組み立てた名前（common/names.py）と、実行時に取る値（user など）だけ。
接続名・アカウント識別子・ユーザー名を SQL のファイルに書かない。未定義の変数が残れば止める。
"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

from .names import Names
from .paths import HOME

SQL_DIR = HOME / "sql"
_VAR = re.compile(r"<%\s*([a-z_]+)\s*%>")
# SQL の識別子に入れてよい値（名前は接頭辞から作るので英大文字・数字・_ だけ。ユーザー名は引用して渡す）
_IDENT = re.compile(r"^[A-Z][A-Z0-9_]{0,254}$")


class SqlTemplateError(ValueError):
    pass


_IMAGE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


def variables(
    names: Names,
    *,
    warehouse_size: str,
    user: str | None = None,
    compute_pool_family: str = "CPU_X64_XS",
    image_name: str = "jpcalc",
) -> dict[str, str]:
    v = {k: str(x) for k, x in asdict(names).items()}
    v["warehouse_size"] = warehouse_size
    v["compute_pool_family"] = compute_pool_family
    if not _IMAGE_NAME.match(image_name):
        raise SqlTemplateError(f"イメージ名は英小文字・数字・_ - だけ: {image_name!r}")
    if user is not None:
        if not user or len(user) > 255:
            raise SqlTemplateError("ユーザー名が空か長すぎる")
        # ユーザー名は引用符つきの識別子として差し込む（大文字小文字・記号をそのまま扱う）
        v["user"] = '"' + user.replace('"', '""') + '"'
    for k, x in v.items():
        if k not in ("user",) and not _IDENT.match(x):
            raise SqlTemplateError(f"SQL に差し込めない名前: {k}={x!r}")
    v["image_name"] = image_name  # 検査済み（英小文字）。_IDENT の検査の後に足す
    return v


def render(text: str, values: dict[str, str]) -> str:
    missing = sorted({m.group(1) for m in _VAR.finditer(text)} - set(values))
    if missing:
        raise SqlTemplateError(f"SQL のひな型に値の無い変数がある: {missing}")
    return _VAR.sub(lambda m: values[m.group(1)], text)


def render_file(rel: str, values: dict[str, str]) -> str:
    return render((SQL_DIR / rel).read_text(encoding="utf-8"), values)


def split_statements(sql: str) -> list[str]:
    """; で文に分ける。$$ … $$ の中と、-- のコメント行は分けない（コメントだけの文は捨てる）。"""
    out, buf, in_dollar = [], [], False
    for line in sql.splitlines():
        if not in_dollar and line.lstrip().startswith("--"):
            continue
        buf.append(line)
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        if not in_dollar and line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt.rstrip(";").strip():
                out.append(stmt)
            buf = []
    rest = "\n".join(buf).strip()
    if rest:
        out.append(rest)
    return out


SETUP_FILES = (
    "setup/00_roles.sql",
    "setup/01_objects.sql",
    "setup/02_grants.sql",
    "setup/03_containers.sql",
    "procedures/ai_call.sql",
    "procedures/steps.sql",
    "procedures/evaluate.sql",
    "tasks/dag.sql",
)
VERIFY_FILE = "verify/roles.sql"


def all_files() -> list[Path]:
    return sorted(SQL_DIR.rglob("*.sql"))

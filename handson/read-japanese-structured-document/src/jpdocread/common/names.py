"""Snowflake のオブジェクト名（命名規則：接頭辞 NAME_PREFIX から組み立てる）。

configs/deploy.env の `NAME_PREFIX` だけを出所とし、DB・スキーマ・ロール・WH・プールの名前をここで組み立てる。
アカウントレベルのオブジェクトとスキーマは接頭辞で始め、スキーマ内のオブジェクトは完全修飾名で一意にする。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from pathlib import Path

from .envfile import read_env_file
from .paths import DEPLOY_ENV

_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*_$")
# 命名規則：自前の名前に snow / snowflake を含めない
_BANNED_WORD_RE = re.compile(r"snow", re.IGNORECASE)


class NamingError(ValueError):
    """命名規則に反する。"""


@dataclass(frozen=True)
class Names:
    prefix: str

    # アカウントレベルのオブジェクト
    db: str
    eval_db: str
    role_admin: str
    role_predict: str
    role_eval: str
    warehouse: str
    compute_pool: str

    # スキーマ（DB 名を含まない短い名前）
    schema_raw: str
    schema_parsed: str
    schema_output: str
    schema_ops: str
    schema_app: str
    schema_gold: str
    schema_results: str

    def account_objects(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "prefix"}

    def fq(self, schema_attr: str, obj: str | None = None) -> str:
        """スキーマ（と、あればその中のオブジェクト）の完全修飾名を返す。"""
        schema = getattr(self, schema_attr)
        db = self.eval_db if schema_attr in ("schema_gold", "schema_results") else self.db
        return f"{db}.{schema}" + (f".{obj}" if obj else "")


def build_names(prefix: str) -> Names:
    """接頭辞から全ての名前を組み立て、命名規則を検査して返す。"""
    if not _PREFIX_RE.match(prefix):
        raise NamingError(f"NAME_PREFIX は大文字・数字・_ からなり、_ で終わること: {prefix!r}")
    names = Names(
        prefix=prefix,
        db=f"{prefix}DB",
        eval_db=f"{prefix}EVAL_DB",
        role_admin=f"{prefix}ADMIN",
        role_predict=f"{prefix}PREDICT",
        role_eval=f"{prefix}EVAL_ROLE",
        warehouse=f"{prefix}WH",
        compute_pool=f"{prefix}POOL",
        schema_raw=f"{prefix}RAW",
        schema_parsed=f"{prefix}PARSED",
        schema_output=f"{prefix}OUTPUT",
        schema_ops=f"{prefix}OPS",
        schema_app=f"{prefix}APP",
        schema_gold=f"{prefix}GOLD",
        schema_results=f"{prefix}RESULTS",
    )
    check_names(names)
    return names


def check_names(names: Names) -> None:
    for key, value in names.account_objects().items():
        if not value.startswith(names.prefix):
            raise NamingError(f"{key}={value} が接頭辞 {names.prefix} で始まらない")
        if _BANNED_WORD_RE.search(value):
            raise NamingError(f"{key}={value} に禁止語（snow）が含まれる")
    values = list(names.account_objects().values())
    if len(set(values)) != len(values):
        dups = sorted({v for v in values if values.count(v) > 1})
        raise NamingError(
            f"名前が重複している: {dups}（configs/deploy.env の名前の設定を確かめる）"
        )


def load_names(deploy_env: Path = DEPLOY_ENV) -> Names:
    env = read_env_file(deploy_env)
    prefix = env.get("NAME_PREFIX")
    if not prefix:
        raise NamingError(
            f"{deploy_env} に NAME_PREFIX が無い（configs/deploy.env.example を参照）"
        )
    return build_names(prefix)

"""生成コードの識別子の検査（関数名・入力名・定数と表のキー）。

codegen は関数名と入力名をそのまま Python の名前にし、定数と表のキーは接頭辞を付けて大文字にする。
名前が予約語だったり、生成モジュールの先頭が定義する補助の名前（tri の t_add・_norm・_OMIT など）や組み込みと
重なったりすると、モジュールが構文エラーになるか、関数が補助を隠して結果が変わる。ここで 1 つの規則で落とす。
"""

from __future__ import annotations

import ast
import builtins
import keyword
import re
from functools import cache

NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
# 定数と表のキー（codegen が P_・T_ を付けて大文字にする）。ASCII に限り、大文字にしても衝突しないことを別に確かめる
KEY = re.compile(r"^[A-Za-z0-9_]{1,80}$")
# codegen がモジュールの先頭に書く名前（tri のソースの外）
_HEADER = ("_OMIT", "_norm")


@cache
def reserved() -> frozenset[str]:
    """生成モジュールの先頭が定義する名前（tri の関数・import・codegen の番兵）。tri のソースから集める。"""
    from . import codegen

    names = set(_HEADER)
    for n in ast.parse(codegen._tri_source()).body:
        if isinstance(n, ast.FunctionDef | ast.ClassDef):
            names.add(n.name)
        elif isinstance(n, ast.Import | ast.ImportFrom):
            names.update(a.asname or a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return frozenset(names)


def name_problem(name, *, role: str) -> str | None:
    """関数名（role="function"）か入力名（role="input"）として使えなければ理由を返す。"""
    if not isinstance(name, str) or not NAME.match(name):
        return f"identifier {name!r} must match {NAME.pattern}"
    if keyword.iskeyword(name):
        return f"identifier {name!r} is a Python keyword"
    if name in reserved():
        return f"identifier {name!r} collides with a helper of the generated module"
    if role == "function" and hasattr(builtins, name):
        return f"identifier {name!r} shadows a builtin used by the generated module"
    return None


def _called_rules(r: dict) -> set[str]:
    out: set[str] = set()

    def walk(e):
        if isinstance(e, dict):
            if "rule" in e and "op" not in e:
                out.add(e["rule"])
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)

    walk([s.get("expr") for s in r.get("steps") or [] if isinstance(s, dict)])
    return out


def spec_problems(spec: dict) -> list[str]:
    """仕様の中の名前の問題（関数に帰属するものは関数名を前に付ける。usable_subset がその関数だけを外せるように）。"""
    probs: list[str] = []
    rules = spec.get("rules") or []
    for r in rules:
        fn = r.get("function")
        p = name_problem(fn, role="function")
        if p:
            probs.append(f"{fn}: {p}")
        calls = _called_rules(r)
        for i in r.get("inputs") or []:
            nm = i.get("name")
            p = name_problem(nm, role="input")
            if p is None and nm in calls:
                # 生成コードでは、入力が同じ名前の関数を隠し、呼び出しが失敗する（インタプリタとは結果が違う）
                p = f"identifier {nm!r} is also the name of a rule this function calls"
            if p:
                probs.append(f"{fn}: input {p}")
    for kind, prefix in (("params", "P_"), ("tables", "T_")):
        seen: dict[str, str] = {}
        for k in spec.get(kind) or {}:
            if not isinstance(k, str) or not KEY.match(k):
                probs.append(f"{kind} key identifier {k!r} must match {KEY.pattern}")
                continue
            emitted = (prefix + k).upper()
            if emitted in seen:
                probs.append(f"{kind} key identifier {k!r} collides with {seen[emitted]!r}")
            seen[emitted] = k
    return probs

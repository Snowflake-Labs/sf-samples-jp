"""生成モジュールの静的検査（sandbox で実行する前に必ず通す）。

生成コードは仕様から決定的に作るので、使う import・属性・構文は決まっている。検査は許可リストで行い、
リストの外の import（モジュールと名前）・属性の参照・構文（class・global・while・try・with・yield など）・
ダンダーの名前の関数と、動的な実行・ファイル・環境への入口となる名前を拒否する。
許可リストは tri のソースと codegen が生成するモジュールが使うものだけにしている（`calendar.sys.modules` のように
許可した import から属性をたどる抜け道を止めるため）。codegen を変えて新しい属性や構文を使うときは、ここも足す。
検査は AST だけで行い、生成コードを本プロセスに読み込まない。
"""

from __future__ import annotations

import ast

# import は丸ごと許すモジュール（属性は ALLOWED_ATTRS で絞る）と、from で許す名前
ALLOWED_IMPORTS = frozenset({"datetime", "calendar"})
ALLOWED_FROM = {"__future__": frozenset({"annotations"}), "fractions": frozenset({"Fraction"})}
# 参照してよい属性（日付・期間・分数・暦・辞書の get）
ALLOWED_ATTRS = frozenset(
    {
        "date",
        "timedelta",
        "year",
        "month",
        "day",
        "days",
        "monthrange",
        "numerator",
        "denominator",
        "get",
    }
)
# 使ってよい構文（tri と生成モジュールが使うものと、害の無い List・Pass・In・NotIn）
ALLOWED_NODES = frozenset(
    {
        "Add",
        "And",
        "Assign",
        "Attribute",
        "AugAssign",
        "BinOp",
        "BitOr",
        "BoolOp",
        "Call",
        "Compare",
        "Constant",
        "Dict",
        "Div",
        "Eq",
        "Expr",
        "FloorDiv",
        "For",
        "FormattedValue",
        "FunctionDef",
        "GeneratorExp",
        "Gt",
        "GtE",
        "If",
        "IfExp",
        "Import",
        "ImportFrom",
        "In",
        "Is",
        "IsNot",
        "JoinedStr",
        "Lambda",
        "List",
        "ListComp",
        "Load",
        "Lt",
        "LtE",
        "Mod",
        "Module",
        "Mult",
        "Name",
        "Not",
        "NotEq",
        "NotIn",
        "Or",
        "Pass",
        "Raise",
        "Return",
        "Starred",
        "Store",
        "Sub",
        "Subscript",
        "Tuple",
        "USub",
        "UnaryOp",
        "alias",
        "arg",
        "arguments",
        "comprehension",
        "keyword",
    }
)
# 生成コードに現れてはならない名前（ファイル・動的評価・内省・プロセスと環境への入口）
FORBIDDEN_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "memoryview",
        "__builtins__",
        "importlib",
        "os",
        "sys",
        "subprocess",
        "type",
        "super",
    }
)
FORBIDDEN_CALLS = FORBIDDEN_NAMES  # 互換のための別名


class CodegenCheckError(ValueError):
    pass


def check_module(src: str) -> list[str]:
    """違反の一覧を返す（空なら合格）。構文エラーも違反として返す。"""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as e:  # ValueError：NUL 文字など
        return [f"構文エラー: {e}"]
    out: list[str] = []
    for n in ast.walk(tree):
        line = getattr(n, "lineno", "-")
        kind = type(n).__name__
        if kind not in ALLOWED_NODES:
            out.append(f"{line}: 許可されない構文 {kind}")
        elif isinstance(n, ast.Import):
            out += [
                f"{line}: 許可されない import {a.name}"
                for a in n.names
                if a.name not in ALLOWED_IMPORTS
            ]
        elif isinstance(n, ast.ImportFrom):
            ok = ALLOWED_FROM.get(n.module or "", frozenset()) if not n.level else frozenset()
            out += [
                f"{line}: 許可されない import {'.' * n.level}{n.module or ''}.{a.name}"
                for a in n.names
                if a.name not in ok
            ]
        elif isinstance(n, ast.FunctionDef) and n.name.startswith("__"):
            out.append(f"{line}: ダンダーの名前の関数 {n.name}")
        elif isinstance(n, ast.Name) and (n.id in FORBIDDEN_NAMES or n.id.startswith("__")):
            out.append(f"{line}: 禁止された名前 {n.id}")
        elif isinstance(n, ast.Attribute) and n.attr not in ALLOWED_ATTRS:
            out.append(f"{line}: 許可されない属性 {n.attr}")
        elif (
            isinstance(n, ast.Subscript)
            and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)
            and n.slice.value.startswith("__")
        ):
            out.append(f"{line}: `__` で始まる添字 {n.slice.value!r}")
    return out


def require_ok(src: str) -> None:
    probs = check_module(src)
    if probs:
        raise CodegenCheckError("生成モジュールが静的検査を通らない: " + "; ".join(probs[:5]))

"""計算仕様 v1 の検証（JSON Schema と意味の検査）。

スキーマ（configs/schema/calc_spec.schema.json）に加えて意味の検査を行う：
未定義の var / param / step / table / rule・item の範囲外使用・演算の引数の数・入力名とタスクカードの一致・
使われない入力・手順の循環（前方参照の禁止）・rule 呼び出しの循環・生成コードの識別子（idents）。
"""

from __future__ import annotations

import json

import jsonschema

from ..common.paths import CONFIGS
from . import idents

OPS_ARITY = {
    "add": (2, None),
    "sub": (2, 2),
    "mul": (2, None),
    "min": (2, None),
    "max": (2, None),
    "muldiv": (3, 3),
    "round_to": (2, 2),
    "if": (3, 3),
    "and": (2, None),
    "or": (2, None),
    "not": (1, 1),
    "ge": (2, 2),
    "gt": (2, 2),
    "le": (2, 2),
    "lt": (2, 2),
    "eq": (2, 2),
    "ne": (2, 2),
    "lookup": (1, 1),
    "coalesce": (2, None),
    "add_days": (2, 2),
    "add_months": (2, 2),
    "end_of_month": (1, 1),
    "days_between": (2, 2),
    "agg": (1, 1),
}
ATOMS = ("var", "param", "step", "lit", "rule", "item")
ROUNDINGS = ("floor", "ceil", "half_up")
AGG_FUNCS = ("sum", "max", "min", "count")


class SpecError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _schema() -> dict:
    return json.loads((CONFIGS / "schema" / "calc_spec.schema.json").read_text(encoding="utf-8"))


def check(spec: dict, cards: list[dict] | None = None) -> list[str]:
    """問題の一覧を返す（空なら合格）。cards を渡すと関数名・入力名の一致も見る。"""
    probs: list[str] = []
    # スキーマの誤りはすべて返す。rules[N] の中の誤りは関数名を前に付け、その関数だけを外せるようにする
    errs = sorted(
        jsonschema.Draft202012Validator(_schema()).iter_errors(spec),
        key=lambda e: [str(x) for x in e.absolute_path],
    )
    if errs:
        out = []
        for e in errs:
            pth = list(e.absolute_path)
            fn = None
            if (
                len(pth) >= 2
                and pth[0] == "rules"
                and isinstance(pth[1], int)
                and isinstance(spec.get("rules"), list)
                and pth[1] < len(spec["rules"])
                and isinstance(spec["rules"][pth[1]], dict)
            ):
                fn = spec["rules"][pth[1]].get("function")
            out.append((f"{fn}: " if isinstance(fn, str) else "") + f"schema: {e.message} at {pth}")
        return out
    params, tables = spec["params"], spec["tables"]
    fns = {r["function"]: r for r in spec["rules"]}
    if len(fns) != len(spec["rules"]):
        probs.append("duplicate function")
    probs += idents.spec_problems(spec)
    for pn, p in params.items():
        if not isinstance(p["value"], int):
            probs.append(f"param {pn}: value must be resolved to an integer (got {p['value']!r})")
    for r in spec["rules"]:
        fn = r["function"]
        inputs = {i["name"]: i for i in r["inputs"]}
        used: set[str] = set()
        defined: list[str] = []

        def walk(e, where, item_fields=None):
            if isinstance(e, bool) or not isinstance(e, dict):
                probs.append(f"{fn}.{where}: expr must be an object, got {e!r}")
                return
            keys = set(e)
            if "op" in e:
                op = e["op"]
                if op not in OPS_ARITY:
                    probs.append(f"{fn}.{where}: unknown op {op!r}")
                    return
                args = e.get("args")
                if not isinstance(args, list):
                    probs.append(f"{fn}.{where}: {op} needs args list")
                    return
                lo, hi = OPS_ARITY[op]
                if len(args) < lo or (hi is not None and len(args) > hi):
                    probs.append(f"{fn}.{where}: {op} arity {len(args)}")
                if op in ("muldiv", "round_to") and e.get("rounding") not in ROUNDINGS:
                    probs.append(f"{fn}.{where}: {op} needs rounding in {ROUNDINGS}")
                if op == "lookup" and e.get("table") not in tables:
                    probs.append(f"{fn}.{where}: unknown table {e.get('table')!r}")
                if op == "agg":
                    over = e.get("over")
                    if e.get("func") not in AGG_FUNCS:
                        probs.append(f"{fn}.{where}: agg func")
                    if over not in inputs or inputs[over]["type"] != "list":
                        probs.append(f"{fn}.{where}: agg over must be a list input")
                        return
                    used.add(over)
                    fields = {f["name"] for f in inputs[over].get("fields", [])}
                    for i, a in enumerate(args):
                        walk(a, f"{where}.{op}[{i}]", fields)
                    return
                for i, a in enumerate(args):
                    walk(a, f"{where}.{op}[{i}]", item_fields)
                return
            atom = [k for k in ATOMS if k in keys]
            if len(atom) != 1:
                probs.append(f"{fn}.{where}: bad atom {e!r}")
                return
            k, v = atom[0], e[atom[0]]
            if k == "var":
                if v not in inputs:
                    probs.append(f"{fn}.{where}: unknown var {v!r}")
                used.add(v)
            elif k == "param" and v not in params:
                probs.append(f"{fn}.{where}: unknown param {v!r}")
            elif k == "step" and v not in defined:
                probs.append(f"{fn}.{where}: step {v!r} not defined before use")
            elif k == "lit" and (isinstance(v, bool) or not isinstance(v, int)):
                probs.append(f"{fn}.{where}: lit must be an integer, got {v!r}")
            elif k == "rule":
                if v not in fns or v == fn:
                    probs.append(f"{fn}.{where}: bad rule call {v!r}")
                else:
                    used.update(set(inputs) & {i["name"] for i in fns[v]["inputs"]})
            elif k == "item" and (item_fields is None or v not in item_fields):
                probs.append(f"{fn}.{where}: item {v!r} outside agg or unknown field")

        for st in r["steps"]:
            if st["name"] in defined or st["name"] in inputs:
                probs.append(f"{fn}: step name {st['name']!r} clashes")
            walk(st["expr"], st["name"])
            defined.append(st["name"])
        if r["output"] not in defined:
            probs.append(f"{fn}: output {r['output']!r} is not a step")
        unused = set(inputs) - used
        if unused:
            probs.append(f"{fn}: unused inputs {sorted(unused)}")
    # rule 呼び出しの循環
    graph = {r["function"]: _rule_refs(r) for r in spec["rules"]}
    seen: dict[str, int] = {}

    def dfs(n):
        seen[n] = 1
        for m in graph.get(n, ()):
            if seen.get(m) == 1:
                probs.append(f"rule cycle via {n} -> {m}")
            elif m not in seen:
                dfs(m)
        seen[n] = 2

    for n in graph:
        if n not in seen:
            dfs(n)
    if cards is not None:
        probs += check_against_cards(spec, cards)
    return probs


# 式に直接書いてよい整数（構造上の数：0 円の下限・日数の調整・百分率）。D のプロンプトと同じ。
# それ以外の数は値スパン（param）を参照させる。手元の仕様の 13.7% の関数がほかの数（12・1000・-1 など）を使って
# いたので、落とさずに警告として記録する（自己テストと採点の結果は変えない）
STRUCTURAL_LITS = frozenset({0, 1, 100})


def warnings(spec: dict) -> list[str]:
    """仕様の警告（合否に使わない記録）：構造上の数でない整数リテラル。"""
    out: list[str] = []
    for r in spec.get("rules") or []:
        fn = r.get("function")
        seen: list[int] = []

        def walk(e):
            if isinstance(e, dict):
                if "lit" in e and "op" not in e and e["lit"] not in STRUCTURAL_LITS:
                    seen.append(e["lit"])
                for v in e.values():
                    walk(v)
            elif isinstance(e, list):
                for v in e:
                    walk(v)

        walk([st.get("expr") for st in r.get("steps") or [] if isinstance(st, dict)])
        if seen:
            out.append(
                f"{fn}: lit outside {sorted(STRUCTURAL_LITS)} (use a value span): {sorted(set(seen))[:5]}"
            )
    return out


def _rule_refs(r: dict) -> set[str]:
    out = set()

    def walk(e):
        if isinstance(e, dict):
            if "rule" in e and "op" not in e:
                out.add(e["rule"])
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)

    walk([s["expr"] for s in r["steps"]])
    return out


def check_against_cards(spec: dict, cards: list[dict]) -> list[str]:
    probs = []
    fns = {r["function"]: r for r in spec["rules"]}
    for c in cards:
        r = fns.get(c["function"])
        if r is None:
            probs.append(f"missing function {c['function']}")
            continue
        want = [(i["name"], i["type"]) for i in c["inputs"]]
        got = [(i["name"], i["type"]) for i in r["inputs"]]
        if sorted(want) != sorted(got):
            probs.append(f"{c['function']}: inputs {got} != card {want}")
        # 欄が無いときも落とす（生成コードの戻り値の型注釈が既定の int になり、カードと食い違うため）
        if r.get("output_type") != c["output"]["type"]:
            probs.append(
                f"{c['function']}: output_type {r.get('output_type')} != card {c['output']['type']}"
            )
    return probs

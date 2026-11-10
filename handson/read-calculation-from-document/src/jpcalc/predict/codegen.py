"""計算仕様 → Python モジュール（決定的なコード生成）。

決定的なテンプレート生成。tri の補助関数を生成モジュールに同梱するので、モジュール単体で動く。
関数名はタスクカードの function、引数はキーワード専用。docstring に根拠、定数に根拠のコメントを付ける。
"""

from __future__ import annotations

import inspect
import keyword
import unicodedata

from ..common import tri

CMP = ("ge", "gt", "le", "lt", "eq", "ne")
SIMPLE = {
    "add": "t_add",
    "sub": "t_sub",
    "mul": "t_mul",
    "min": "t_min",
    "max": "t_max",
    "and": "t_and",
    "or": "t_or",
    "not": "t_not",
    "add_days": "t_add_days",
    "add_months": "t_add_months",
    "end_of_month": "t_end_of_month",
    "days_between": "t_days_between",
}


def _text(s, *, doc: bool = False) -> str:
    """コメント・docstring に入れる文字列（AI の出力・PDF の表記）を 1 行の無害な文字列にする。

    Python のソースでは \\r も行の区切りになるので、制御文字・行と段落の区切り（Cc・Zl・Zp）と
    サロゲート（Cs）を空白にする。docstring の中では、閉じの引用符とエスケープにならないよう " と \\ を除く。
    これで、仕様の文字列はコメントと docstring の外に出ない（文にならない）。
    """
    s = "" if s is None else str(s)
    out = "".join(" " if unicodedata.category(ch) in ("Cc", "Cs", "Zl", "Zp") else ch for ch in s)
    if doc:
        out = out.replace('"', "").replace("\\", "")
    return out


def _ident(prefix: str, name: str) -> str:
    s = prefix + "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return s + "_" if keyword.iskeyword(s) else s


def _excl(i: dict) -> bool:
    """除外事由の真偽の引数か（合成カードの exclusion。bool に限る）。"""
    return bool(i.get("exclusion")) and i.get("type") == "bool"


def _tri_source() -> str:
    src = inspect.getsource(tri)
    return src.split('"""', 2)[2].lstrip("\n")  # モジュールの docstring を外す


class _Gen:
    def __init__(self, spec: dict):
        self.spec = spec
        self.fns = {r["function"]: r for r in spec["rules"]}

    def expr(self, e, rule, item_var=None) -> str:
        if "op" not in e:
            if "var" in e:
                return _ident("v_", e["var"])
            if "param" in e:
                return _ident("P_", e["param"]).upper()
            if "step" in e:
                return _ident("s_", e["step"])
            if "lit" in e:
                return repr(int(e["lit"]))
            if "item" in e:
                return f"t_item({item_var}, {e['item']!r})"
            if "rule" in e:
                callee = self.fns[e["rule"]]
                mine = {i["name"] for i in rule["inputs"]}
                kws = ", ".join(
                    f"{i['name']}={_ident('v_', i['name'])}"
                    for i in callee["inputs"]
                    if i["name"] in mine
                )
                return f"{e['rule']}({kws})"
            raise ValueError(f"bad atom {e}")
        op, args = e["op"], e["args"]
        sub = [self.expr(a, rule, item_var) for a in args] if op != "agg" else []
        if op == "if":
            return f"t_if({sub[0]}, lambda: {sub[1]}, lambda: {sub[2]})"
        if op == "coalesce":
            return "t_coalesce(" + ", ".join(f"lambda: {s}" for s in sub) + ")"
        if op == "agg":
            body = self.expr(args[0], rule, "_it")
            return f"t_agg({e['func']!r}, {_ident('v_', e['over'])}, lambda _it: {body})"
        if op == "lookup":
            t = self.spec["tables"][e["table"]]
            return f"t_lookup({_ident('T_', e['table']).upper()}, {sub[0]}, {t['mode']!r})"
        if op in CMP:
            return f"t_cmp({op!r}, {sub[0]}, {sub[1]})"
        if op in SIMPLE:
            return f"{SIMPLE[op]}({', '.join(sub)})"
        if op in ("muldiv", "round_to"):
            return f"t_{op}({', '.join(sub)}, {e['rounding']!r})"
        raise ValueError(f"unknown op {op}")

    def function(self, r) -> str:
        ann = {
            "int": "int | None",
            "bool": "bool | None",
            "date": "_dt.date | None",
            "list": "list | None",
        }
        # 除外事由の引数は「渡されなかった」と「None（不明）」を区別する（conventions の omitted）
        sig = ", ".join(
            f"{i['name']}: {ann[i['type']]} = {'_OMIT' if _excl(i) else 'None'}"
            for i in r["inputs"]
        )
        out_t = ann.get(r.get("output_type") or "int", "object")
        srcs = _text("; ".join(str(u) for u in r.get("evidence_units") or []), doc=True)
        lines = [
            f"def {r['function']}(*, {sig}) -> {out_t}:"
            if sig
            else f"def {r['function']}() -> {out_t}:",
            f'    """{_text(r.get("title") or r["function"], doc=True)}',
            "",
            f"    根拠: {srcs}",
            '    """',
        ]
        for i in r["inputs"]:
            if _excl(i):
                lines.append(
                    f"    {_ident('v_', i['name'])} = False if {i['name']} is _OMIT else {i['name']}  # 渡されなければ該当しない"
                )
            else:
                lines.append(f"    {_ident('v_', i['name'])} = {i['name']}")
        for st in r["steps"]:
            label = _text(st.get("label")).strip()
            lines.append(
                f"    {_ident('s_', st['name'])} = {self.expr(st['expr'], r)}"
                + (f"  # {label}" if label else "")
            )
        lines.append(f"    return _norm({_ident('s_', r['output'])})")
        return "\n".join(lines)

    def module(self) -> str:
        sp = self.spec
        out = [
            '"""自動生成コード（jpcalc codegen。手で編集しない）。',
            "",
            f"文書: {_text(sp['doc_id'], doc=True)}",
            '"""',
            "",
            _tri_source(),
            "",
            "_OMIT = object()  # 渡されなかった除外事由の印（conventions の omitted）",
            "",
            "def _norm(v):",
            "    from fractions import Fraction",
            "    if isinstance(v, Fraction) and v.denominator == 1:",
            "        return int(v)",
            "    return v",
            "",
            "# ---- 定数（文書から決定的に解決。根拠を併記）",
        ]
        for k, p in sp["params"].items():
            src = _text((p.get("source") or {}).get("unit", ""))
            out.append(
                f"{_ident('P_', k).upper()} = {int(p['value'])!r}  # {_text(p.get('text'))} [{_text(p['unit'])}] 根拠: {src}"
            )
        out.append("")
        out.append("# ---- 参照表")
        for k, t in sp["tables"].items():
            rows = tuple(tuple(int(x) for x in r) for r in t["rows"])
            out.append(
                f"{_ident('T_', k).upper()} = {rows!r}  # {_text(t.get('block_id'))} {_text(t['mode'])}"
            )
        out.append("")
        for r in sp["rules"]:
            out += ["", self.function(r), ""]
        return "\n".join(out) + "\n"


def generate(spec: dict) -> str:
    return _Gen(spec).module()

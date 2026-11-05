"""計算仕様の参照インタプリタ。式の木を tri の補助関数で直接評価する。

T 段の期待値の計算に使い、codegen の生成コードと突き合わせて I 段の誤りを捕まえる。
"""

from __future__ import annotations

from ..common import tri as T

CMP = ("ge", "gt", "le", "lt", "eq", "ne")


class Interp:
    def __init__(self, spec: dict):
        self.spec = spec
        self.fns = {r["function"]: r for r in spec["rules"]}
        self.params = {k: p["value"] for k, p in spec["params"].items()}
        self.tables = {
            k: (tuple(tuple(r) for r in t["rows"]), t["mode"]) for k, t in spec["tables"].items()
        }

    def call(self, function: str, **kwargs):
        r = self.fns[function]
        # 渡されなかった除外事由は該当しない（False）とみなす。None が渡されたら不明のまま（conventions の omitted）
        env = {
            i["name"]: (
                False
                if i["name"] not in kwargs and i.get("exclusion") and i.get("type") == "bool"
                else kwargs.get(i["name"])
            )
            for i in r["inputs"]
        }
        steps: dict = {}
        for st in r["steps"]:
            steps[st["name"]] = self._ev(st["expr"], env, steps, None, r)
        out = steps[r["output"]]
        return _normalize(out)

    def _ev(self, e, env, steps, item, rule):
        if "op" not in e:
            if "var" in e:
                return env[e["var"]]
            if "param" in e:
                return self.params[e["param"]]
            if "step" in e:
                return steps[e["step"]]
            if "lit" in e:
                return e["lit"]
            if "item" in e:
                return T.t_item(item, e["item"])
            if "rule" in e:
                callee = self.fns[e["rule"]]
                # 呼び出し元に同じ名前の入力があるものだけを渡す（codegen と同じ。渡さない除外事由は呼ばれる側で
                # 「該当しない」になる。conventions の omitted・独立レビューの指摘）
                return self.call(
                    e["rule"],
                    **{i["name"]: env[i["name"]] for i in callee["inputs"] if i["name"] in env},
                )
            raise ValueError(f"bad atom {e}")
        op, args = e["op"], e["args"]

        def ev(a):
            return self._ev(a, env, steps, item, rule)

        if op == "if":
            return T.t_if(ev(args[0]), lambda: ev(args[1]), lambda: ev(args[2]))
        if op == "coalesce":
            return T.t_coalesce(*[(lambda a=a: ev(a)) for a in args])
        if op == "agg":
            items = env[e["over"]]
            return T.t_agg(e["func"], items, lambda it: self._ev(args[0], env, steps, it, rule))
        if op == "lookup":
            rows, mode = self.tables[e["table"]]
            return T.t_lookup(rows, ev(args[0]), mode)
        vals = [ev(a) for a in args]
        if op in CMP:
            return T.t_cmp(op, *vals)
        f = {
            "add": T.t_add,
            "sub": T.t_sub,
            "mul": T.t_mul,
            "min": T.t_min,
            "max": T.t_max,
            "and": T.t_and,
            "or": T.t_or,
            "not": T.t_not,
            "add_days": T.t_add_days,
            "add_months": T.t_add_months,
            "end_of_month": T.t_end_of_month,
            "days_between": T.t_days_between,
        }.get(op)
        if f:
            return f(*vals)
        if op == "muldiv":
            return T.t_muldiv(*vals, e["rounding"])
        if op == "round_to":
            return T.t_round_to(*vals, e["rounding"])
        raise ValueError(f"unknown op {op}")


def _normalize(v):
    from fractions import Fraction

    if isinstance(v, Fraction) and v.denominator == 1:
        return int(v)
    return v

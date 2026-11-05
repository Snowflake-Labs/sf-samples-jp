"""手書きの計算仕様（仕様・インタプリタ・codegen の単体テスト用。どの文書の正解でもない）。"""

import copy


def _p(v, unit="JPY"):
    return {"value": v, "unit": unit}


def card(fn, inputs, out="int"):
    return {"function": fn, "inputs": inputs, "output": {"type": out}}


def I(name, t="int", **kw):  # noqa: E743
    return {"name": name, "type": t, **kw}


S1 = {  # 実費 − 免責、限度、0 円下限
    "spec_version": "jpcalc-1",
    "doc_id": "fx1",
    "params": {"ded": _p(10000), "lim": _p(300000)},
    "tables": {},
    "rules": [
        {
            "function": "pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("a", min=0, max=1000000), I("b", min=0, max=1000000)],
            "steps": [
                {"name": "total", "expr": {"op": "add", "args": [{"var": "a"}, {"var": "b"}]}},
                {
                    "name": "net",
                    "expr": {"op": "sub", "args": [{"step": "total"}, {"param": "ded"}]},
                },
                {
                    "name": "capped",
                    "expr": {"op": "min", "args": [{"step": "net"}, {"param": "lim"}]},
                },
                {"name": "out", "expr": {"op": "max", "args": [{"lit": 0}, {"step": "capped"}]}},
            ],
            "output": "out",
        }
    ],
}
C1 = [card("pay", [I("a", min=0, max=1000000), I("b", min=0, max=1000000)])]

S2 = {  # 表引き（等級）× 割合 → 端数処理
    "spec_version": "jpcalc-1",
    "doc_id": "fx2",
    "params": {"unit": _p(1000)},
    "tables": {
        "rate": {"rows": [[1, 100], [2, 90], [3, 80]], "mode": "exact"},
        "dec": {"rows": [[2, 90], [4, 80], [6, 70]], "mode": "step_le"},
    },
    "rules": [
        {
            "function": "grade_pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("amt", min=0, max=50000000), I("grade", min=1, max=4)],
            "steps": [
                {
                    "name": "r",
                    "expr": {"op": "lookup", "table": "rate", "args": [{"var": "grade"}]},
                },
                {
                    "name": "g",
                    "expr": {
                        "op": "muldiv",
                        "rounding": "floor",
                        "args": [{"var": "amt"}, {"step": "r"}, {"lit": 100}],
                    },
                },
                {
                    "name": "out",
                    "expr": {
                        "op": "round_to",
                        "rounding": "floor",
                        "args": [{"step": "g"}, {"param": "unit"}],
                    },
                },
            ],
            "output": "out",
        },
        {
            "function": "dec_pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("amt", min=0, max=50000000), I("years", min=0, max=10)],
            "steps": [
                {"name": "r", "expr": {"op": "lookup", "table": "dec", "args": [{"var": "years"}]}},
                {
                    "name": "out",
                    "expr": {
                        "op": "muldiv",
                        "rounding": "floor",
                        "args": [{"var": "amt"}, {"step": "r"}, {"lit": 100}],
                    },
                },
            ],
            "output": "out",
        },
    ],
}
C2 = [
    card("grade_pay", [I("amt", min=0, max=50000000), I("grade", min=1, max=4)]),
    card("dec_pay", [I("amt", min=0, max=50000000), I("years", min=0, max=10)]),
]

S3 = {  # 判定（Kleene）と判定を使う計算
    "spec_version": "jpcalc-1",
    "doc_id": "fx3",
    "params": {"min_days": _p(5, "DAY"), "daily": _p(2000, "JPY/DAY"), "max_days": _p(25, "DAY")},
    "tables": {},
    "rules": [
        {
            "function": "elig",
            "kind": "decision",
            "output_type": "bool",
            "inputs": [I("damaged", "bool"), I("days", min=0, max=60), I("paid_elsewhere", "bool")],
            "steps": [
                {
                    "name": "out",
                    "expr": {
                        "op": "and",
                        "args": [
                            {"var": "damaged"},
                            {"op": "ge", "args": [{"var": "days"}, {"param": "min_days"}]},
                            {"op": "not", "args": [{"var": "paid_elsewhere"}]},
                        ],
                    },
                }
            ],
            "output": "out",
        },
        {
            "function": "elig_pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("damaged", "bool"), I("days", min=0, max=60), I("paid_elsewhere", "bool")],
            "steps": [
                {
                    "name": "d",
                    "expr": {"op": "min", "args": [{"var": "days"}, {"param": "max_days"}]},
                },
                {"name": "g", "expr": {"op": "mul", "args": [{"param": "daily"}, {"step": "d"}]}},
                {
                    "name": "out",
                    "expr": {"op": "if", "args": [{"rule": "elig"}, {"step": "g"}, {"lit": 0}]},
                },
            ],
            "output": "out",
        },
    ],
}
C3 = [
    card(
        "elig",
        [I("damaged", "bool"), I("days", min=0, max=60), I("paid_elsewhere", "bool")],
        "bool",
    ),
    card("elig_pay", [I("damaged", "bool"), I("days", min=0, max=60), I("paid_elsewhere", "bool")]),
]

S4 = {  # 期限（日付）と証券の記載による上書き
    "spec_version": "jpcalc-1",
    "doc_id": "fx4",
    "params": {"days": _p(30, "DAY"), "default_lim": _p(500000)},
    "tables": {},
    "rules": [
        {
            "function": "deadline",
            "kind": "calculation",
            "output_type": "date",
            "inputs": [I("doc_date", "date")],
            "steps": [
                {
                    "name": "out",
                    "expr": {
                        "op": "add_days",
                        "args": [
                            {"var": "doc_date"},
                            {"op": "sub", "args": [{"param": "days"}, {"lit": 1}]},
                        ],
                    },
                }
            ],
            "output": "out",
        },
        {
            "function": "lim_pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("cost", min=0, max=2000000), I("policy_limit", min=0, max=2000000)],
            "steps": [
                {
                    "name": "lim",
                    "expr": {
                        "op": "coalesce",
                        "args": [{"var": "policy_limit"}, {"param": "default_lim"}],
                    },
                },
                {"name": "out", "expr": {"op": "min", "args": [{"var": "cost"}, {"step": "lim"}]}},
            ],
            "output": "out",
        },
    ],
}
C4 = [
    card("deadline", [I("doc_date", "date")], "date"),
    card("lim_pay", [I("cost", min=0, max=2000000), I("policy_limit", min=0, max=2000000)]),
]

S5 = {  # 明細の集計
    "spec_version": "jpcalc-1",
    "doc_id": "fx5",
    "params": {"sub": _p(50000), "tot": _p(150000)},
    "tables": {},
    "rules": [
        {
            "function": "items_pay",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [I("items", "list", fields=[I("x", min=0, max=100000)], max_items=4)],
            "steps": [
                {
                    "name": "s",
                    "expr": {
                        "op": "agg",
                        "func": "sum",
                        "over": "items",
                        "args": [{"op": "min", "args": [{"item": "x"}, {"param": "sub"}]}],
                    },
                },
                {"name": "out", "expr": {"op": "min", "args": [{"step": "s"}, {"param": "tot"}]}},
            ],
            "output": "out",
        }
    ],
}
C5 = [card("items_pay", [I("items", "list", fields=[I("x", min=0, max=100000)], max_items=4)])]

GOOD = [(S1, C1), (S2, C2), (S3, C3), (S4, C4), (S5, C5)]


def broken():
    out = []

    def mk(base, f):
        s = copy.deepcopy(base)
        f(s)
        out.append(s)

    mk(
        S1, lambda s: s["rules"][0]["steps"][0]["expr"]["args"].__setitem__(0, {"var": "zzz"})
    )  # 未定義 var
    mk(
        S1, lambda s: s["rules"][0]["steps"][1]["expr"]["args"].__setitem__(1, {"param": "nope"})
    )  # 未定義 param
    mk(
        S1, lambda s: s["rules"][0]["steps"][0]["expr"]["args"].__setitem__(0, {"step": "net"})
    )  # 前方参照
    mk(S1, lambda s: s["rules"][0]["steps"][1]["expr"].update(op="frobnicate"))  # 未知の演算
    mk(S2, lambda s: s["rules"][0]["steps"][1]["expr"].pop("rounding"))  # 端数処理なし
    mk(S2, lambda s: s["rules"][0]["steps"][0]["expr"].update(table="missing"))  # 未定義の表
    mk(S3, lambda s: s["rules"][0]["steps"][0]["expr"]["args"].pop(0))  # 使われない入力
    mk(
        S3, lambda s: s["rules"][1]["steps"][2]["expr"]["args"].__setitem__(0, {"rule": "elig_pay"})
    )  # 自己呼び出し
    mk(
        S5, lambda s: s["rules"][0]["steps"][0]["expr"]["args"].__setitem__(0, {"item": "y"})
    )  # 未知の明細項目
    mk(S1, lambda s: s["params"]["ded"].update(value="1万円"))  # 値が未解決
    return out

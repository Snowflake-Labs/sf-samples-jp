"""k_lint の旗：立つ場合と立たない場合の対（架空のカード）。"""

from __future__ import annotations

import pytest

from jpcalc.predict.k_lint import lint_card, lint_cards


def _flags(card):
    return {f["flag"] for f in lint_card(card)}


def I(name, t="int", **kw):  # noqa: E743
    return {"name": name, "type": t, "desc": kw.pop("desc", name), **kw}


@pytest.mark.parametrize(
    ("flag", "bad", "good"),
    [
        (
            "base_quantity_missing",
            {
                "kind": "calculation",
                "output": {"unit": "JPY"},
                "inputs": [I("paid", unit="JPY", desc="既に支払った額")],
            },
            {
                "kind": "calculation",
                "output": {"unit": "JPY"},
                "inputs": [
                    I("loss", unit="JPY", desc="損害の額"),
                    I("paid", unit="JPY", desc="既に支払った額"),
                ],
            },
        ),
        (
            "affirmative_condition_missing",
            {
                "kind": "decision",
                "inputs": [I("intent", "bool", exclusion=True, desc="故意によること")],
            },
            {
                "kind": "decision",
                "inputs": [
                    I("accident", "bool", desc="事故が生じたこと"),
                    I("intent", "bool", exclusion=True, desc="故意によること"),
                ],
            },
        ),
        (
            "bundled_input",
            {
                "kind": "decision",
                "inputs": [I("any_excl", "bool", desc="次のいずれかに該当すること")],
            },
            {"kind": "decision", "inputs": [I("war", "bool", desc="戦争によること")]},
        ),
        (
            "condition_in_amount",
            {
                "kind": "calculation",
                "output": {"unit": "JPY"},
                "inputs": [
                    I("loss", unit="JPY", desc="損害の額"),
                    I("ok", "bool", desc="支払の要件を満たすこと"),
                ],
            },
            {
                "kind": "calculation",
                "output": {"unit": "JPY"},
                "inputs": [
                    I("loss", unit="JPY", desc="損害の額"),
                    I("intent", "bool", exclusion=True, desc="故意によること"),
                ],
            },
        ),
        (
            "policy_period_input",
            {
                "kind": "decision",
                "inputs": [
                    I("start", "date", desc="保険期間の開始日"),
                    I("acc", "bool", desc="事故"),
                ],
            },
            {
                "kind": "decision",
                "inputs": [I("acc_date", "date", desc="事故の日"), I("acc", "bool", desc="事故")],
            },
        ),
        (
            "negated_requirement",
            {
                "kind": "decision",
                "inputs": [I("no_treat", "bool", desc="医師の治療を伴わないこと")],
            },
            {"kind": "decision", "inputs": [I("treated", "bool", desc="医師の治療を受けたこと")]},
        ),
    ],
)
def test_flag_pairs(flag, bad, good):
    assert flag in _flags(bad)
    assert flag not in _flags(good)


def test_defined_quantity():
    ev = "経過月数に応じて返還率を定める。"
    as_date = {
        "kind": "calculation",
        "evidence_text": ev,
        "inputs": [I("start", "date", desc="契約日")],
    }
    missing = {"kind": "calculation", "evidence_text": ev, "inputs": [I("x", desc="保険料")]}
    ok = {
        "kind": "calculation",
        "evidence_text": ev,
        "inputs": [I("months", unit="MONTH", desc="経過月数")],
    }
    assert "defined_quantity_as_date" in _flags(as_date)
    assert "defined_quantity_missing" in _flags(missing)
    assert not {"defined_quantity_as_date", "defined_quantity_missing"} & _flags(ok)


def test_example_quantity_unused():
    card = {
        "kind": "calculation",
        "output": {"unit": "JPY"},
        # 設例の文は pdoc と同じく値を値スパン（{const:…}）に置き換えた形
        "example_text": ["治療費の額が{const:v001}のとき、保険金は{const:v002}となります。"],
        "inputs": [I("x", unit="JPY", desc="見舞金の基準")],
    }
    ok = dict(card, inputs=[I("cost", unit="JPY", desc="治療費の額")])
    assert "example_quantity_unused" in _flags(card)
    assert "example_quantity_unused" not in _flags(ok)


def test_lint_cards_counts():
    cards = [
        {
            "function": "f1",
            "kind": "decision",
            "inputs": [I("a", "bool", desc="次のいずれかに該当")],
        },
        {"function": "f2", "kind": "decision", "inputs": [I("b", "bool", desc="事故が生じたこと")]},
    ]
    r = lint_cards(cards)
    assert r["n_cards"] == 2 and r["n_flagged"] == 1 and r["counts"] == {"bundled_input": 1}

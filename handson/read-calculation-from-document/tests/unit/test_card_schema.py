"""合成カードの schema：K が作るカードは合い、壊したカードは落ちる。"""

from __future__ import annotations

import copy

import pytest

from jpcalc.predict import k_cards
from jpcalc.predict.card_schema import check_card

CANDS = [{"id": "p1", "kind": "paragraph", "container": "a1", "text": "x"}]


def _card(**rule):
    r = {
        "function": "pay_amount",
        "title": "保険金の額",
        "kind": "calculation",
        "inputs": [
            {"name": "loss", "type": "int", "unit": "JPY", "desc": "損害の額"},
            {
                "name": "intent",
                "type": "bool",
                "unit": None,
                "exclusion": True,
                "desc": "故意によること",
            },
            {
                "name": "items",
                "type": "list",
                "unit": None,
                "desc": "明細",
                "fields": [{"name": "cost", "type": "int", "unit": "JPY", "desc": "費用"}],
            },
        ],
        "output": {"type": "int"},
        "units": ["p1"],
    }
    r.update(rule)
    cards, _, probs = k_cards.interpret("doc-a", {"rules": [r]}, CANDS)
    assert cards, probs
    return cards[0]


def test_k_cards_fit_schema():
    assert check_card(_card()) == []
    assert check_card(_card(kind="decision", output={"type": "bool"})) == []


def _broken(edit):
    c = copy.deepcopy(_card())
    edit(c)
    return c


@pytest.mark.parametrize(
    ("edit", "where"),
    [
        (lambda c: c.update(function="PayAmount"), "function"),
        (lambda c: c.update(kind="decision"), "output/type"),
        (lambda c: c.update(evidence_units=[]), "evidence_units"),
        (lambda c: c.update(hint="H2"), "hint"),
        (lambda c: c["inputs"][1].update(unit="JPY"), "inputs/1/unit"),
        (lambda c: c["inputs"][0].update(exclusion=True), "inputs/0/type"),
        (lambda c: c["inputs"][2].pop("fields"), "inputs/2"),
        (lambda c: c.pop("evidence_units"), "(root)"),
        (lambda c: c.update(inputs=[]), "inputs"),
    ],
)
def test_broken_cards_fail(edit, where):
    errs = check_card(_broken(edit))
    assert errs and any(f": {where}:" in e for e in errs), errs

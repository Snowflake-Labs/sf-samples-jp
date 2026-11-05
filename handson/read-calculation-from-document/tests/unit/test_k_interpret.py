"""段 K の応答の検査（interpret）・J1 の候補・LLM の応答の解析とキャッシュキー（AI を呼ばない）。"""

from __future__ import annotations

import pytest

from jpcalc.predict import j_detect, k_cards
from jpcalc.predict.llm import Req, parse_json, strip_fence
from jpcalc.predict.policy_index import PolicyIndex

CANDS = [
    {"id": "p1", "kind": "paragraph", "container": "a1", "text": "x"},
    {"id": "p2", "kind": "paragraph", "container": "a1", "text": "y"},
    {"id": "p9", "kind": "paragraph", "container": "a3", "text": "z"},
]


def _rule(**kw):
    r = {
        "function": "pay_amount",
        "title": "保険金の額",
        "kind": "calculation",
        "inputs": [{"name": "loss", "type": "int", "unit": "JPY", "desc": "損害の額"}],
        "output": {"type": "int"},
        "units": ["p1"],
    }
    r.update(kw)
    return r


def _interp(*rules):
    return k_cards.interpret("doc-a", {"rules": list(rules)}, CANDS)


def test_input_name_rule():
    # 入力の名前は英小文字で始まる 2 文字以上（1 文字の名前は拒否する）
    assert (
        k_cards._check_input("f", {"name": "n", "type": "int", "unit": "COUNT"}, set())[0] is None
    )
    assert (
        k_cards._check_input("f", {"name": "nn", "type": "int", "unit": "COUNT"}, set())[0]
        is not None
    )


def test_valid_rule_becomes_card():
    cards, units, probs = _interp(_rule())
    assert [c["function"] for c in cards] == ["pay_amount"] and units == {"pay_amount": ["p1"]}
    c = cards[0]
    assert c["evidence_units"] == ["p1"] and c["hint"] == "auto" and c["inputs"][0]["min"] == 0
    assert not probs


@pytest.mark.parametrize(
    ("rule", "why"),
    [
        (_rule(function="PayAmount"), "bad function name"),
        (_rule(kind="estimate"), "bad kind"),
        (_rule(kind="decision"), "does not fit kind"),
        (_rule(units=["p404"]), "no valid evidence units"),
        (_rule(inputs=[{"name": "loss", "type": "float", "unit": "JPY"}]), "no valid inputs"),
        (_rule(inputs=[{"name": "loss", "type": "int", "unit": "EUR"}]), "no valid inputs"),
    ],
)
def test_invalid_rule_is_rejected(rule, why):
    cards, _, probs = _interp(rule)
    assert cards == [] and any(why in p for p in probs), probs


def test_duplicate_function_keeps_first():
    cards, _, probs = _interp(_rule(), _rule(units=["p2"]))
    assert len(cards) == 1 and cards[0]["evidence_units"] == ["p1"]
    assert any("duplicate function" in p for p in probs)


def test_container_id_expands_to_its_candidates():
    cards, units, _ = _interp(_rule(units=["a1"]))
    assert units["pay_amount"] == ["p1", "p2"]


def test_contract_units_are_accepted():
    # 契約書の単位（時間・分・指数）は規約の語彙にあるので受け付ける
    for u in ("HOUR", "MIN", "INDEX"):
        cards, _, probs = _interp(
            _rule(inputs=[{"name": "qty", "type": "int", "unit": u, "desc": "量"}])
        )
        assert cards and cards[0]["inputs"][0]["unit"] == u, (u, probs)


def test_exclusion_mark_only_on_bool():
    bad = {"name": "n_times", "type": "int", "unit": "COUNT", "exclusion": True, "desc": "回数"}
    ok = {
        "name": "intent",
        "type": "bool",
        "unit": None,
        "exclusion": True,
        "desc": "故意によること",
    }
    cards, _, probs = _interp(_rule(kind="decision", output={"type": "bool"}, inputs=[ok, bad]))
    ins = {i["name"]: i for i in cards[0]["inputs"]}
    assert ins["intent"].get("exclusion") is True and "exclusion" not in ins["n_times"]
    assert any("exclusion on non-bool" in p for p in probs)


def test_no_rules_array():
    assert k_cards.interpret("d", {"x": 1}, CANDS) == ([], {}, ["K: no rules array"])


# ---- J1：決定的な候補検出


def _ix(text):
    return PolicyIndex(
        {
            "meta": {"constants": {"v001": "1万円"}},
            "body": [
                {
                    "id": "a1",
                    "kind": "article",
                    "label": "第1条",
                    "text": "",
                    "children": [
                        {
                            "id": "p1",
                            "kind": "paragraph",
                            "label": "①",
                            "text": text,
                            "children": [],
                            "blocks": [],
                        }
                    ],
                    "blocks": [],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "text",
    [
        "保険金の額は、損害の額から{const:v001}を差し引いた額とします。",
        "損害の額または{const:v001}のいずれか低い額とします。",
    ],
)
def test_j1_picks_calculation_sentences(text):
    assert [c["id"] for c in j_detect.candidates(_ix(text))] == ["p1"]


def test_j1_skips_plain_sentences():
    assert j_detect.candidates(_ix("この約款は日本の法令に準拠します。")) == []


# ---- LLM の応答の解析とキャッシュキー


def test_strip_fence_and_parse():
    assert strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert parse_json('説明\n{"a": [1, 2]}\n以上') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("JSON ではない")


def test_cache_key_depends_on_every_part(monkeypatch):
    monkeypatch.delenv("JPCALC_CACHE_SALT", raising=False)
    base = Req(
        "K", "d", "u", "p", 10, "v1", "m"
    ).cache_key  # cache_key は呼ぶたびに計算する（salt を読む）
    keys = {
        base,
        Req("K", "d", "u", "p2", 10, "v1", "m").cache_key,
        Req("K", "d", "u", "p", 11, "v1", "m").cache_key,
        Req("K", "d", "u", "p", 10, "v2", "m").cache_key,
        Req("K", "d", "u", "p", 10, "v1", "m2").cache_key,
    }
    assert len(keys) == 5
    # 段・文書・単位はキーに入れない（同じプロンプトなら同じ答えを使い回す）
    assert Req("D", "e", "w", "p", 10, "v1", "m").cache_key == base
    monkeypatch.setenv("JPCALC_CACHE_SALT", "s1")
    assert Req("K", "d", "u", "p", 10, "v1", "m").cache_key != base

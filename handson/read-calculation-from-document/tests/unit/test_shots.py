"""few-shot の手本作り（評価側）：位置の写像・値の対応・写せない規則の除外・名前の置き換え。合成のデータだけを使う。"""

from __future__ import annotations

import json

import pytest

from jpcalc.eval import shots as SH
from jpcalc.predict import shots as PS
from jpcalc.predict.policy_index import PolicyIndex

# 1 ページ・2 項の pdoc。p1 に 1万円と 30万円、p2 に 30万円（同じ値が別の項にもある）
PDOC = {
    "meta": {"constants": {"v001": "1万円", "v002": "30万円", "v003": "30万円", "v004": "5日"}},
    "body": [
        {
            "id": "a1",
            "kind": "article",
            "label": "第1条",
            "text": "",
            "src": [{"page": 1, "bbox": [50, 90, 550, 300]}],
            "children": [
                {
                    "id": "p1",
                    "kind": "paragraph",
                    "label": "①",
                    "text": "保険金の額は、損害の額から{const:v001}を差し引いた額とします。ただし、{const:v002}を限度とします。",
                    "src": [{"page": 1, "bbox": [60, 100, 540, 140]}],
                    "children": [],
                    "blocks": [],
                },
                {
                    "id": "p2",
                    "kind": "paragraph",
                    "label": "②",
                    "text": "見舞金は{const:v003}とし、待機期間は{const:v004}とします。",
                    "src": [{"page": 1, "bbox": [60, 150, 540, 190]}],
                    "children": [],
                    "blocks": [],
                },
            ],
            "blocks": [],
        }
    ],
}

LAYOUT = {
    "elements": {
        "g_p1": {"kind": "paragraph", "fragments": [{"page": 1, "bbox": [62, 102, 538, 138]}]},
        "g_p2": {"kind": "paragraph", "fragments": [{"page": 1, "bbox": [62, 152, 538, 188]}]},
        "g_far": {"kind": "paragraph", "fragments": [{"page": 2, "bbox": [62, 152, 538, 188]}]},
    }
}


def _rule(fn, steps, out, sources, inputs=None, kind="calculation", rid=None):
    return {
        "id": rid or fn,
        "title": fn,
        "kind": kind,
        "interface": {"function": fn},
        "inputs": inputs
        or {
            "loss": {
                "type": "int",
                "unit": "JPY",
                "origin": "claim_fact",
                "desc": "損害の額",
                "min": 0,
                "max": 1000000,
            }
        },
        "steps": steps,
        "output": {
            "step": out,
            "type": "int" if kind == "calculation" else "bool",
            "unit": "JPY" if kind == "calculation" else None,
        },
        "obligations": [],
        "sources": [{"unit": u} for u in sources],
    }


def _spec(rules, params):
    return {"spec_version": "x", "params": params, "tables": {}, "rules": rules}


PAY = _rule(
    "pay_amount",
    [
        {"name": "net", "expr": {"op": "sub", "args": [{"var": "loss"}, {"param": "ded"}]}},
        {"name": "cap", "expr": {"op": "min", "args": [{"step": "net"}, {"param": "lim"}]}},
        {"name": "pay", "expr": {"op": "max", "args": [{"step": "cap"}, {"lit": 0}]}},
    ],
    "pay",
    ["g_p1"],
)
PARAMS = {
    "ded": {"surface": "1万円", "source": {"unit": "g_p1"}, "value": 10000, "unit": "JPY"},
    "lim": {"surface": "30万円", "source": {"unit": "g_p1"}, "value": 300000, "unit": "JPY"},
}


def test_map_unit_by_overlap():
    units = SH._pdoc_units(PDOC)
    assert SH.map_unit(LAYOUT, units, "g_p1", SH.BODY_KINDS) == "p1"
    assert SH.map_unit(LAYOUT, units, "g_p2", SH.BODY_KINDS) == "p2"
    assert SH.map_unit(LAYOUT, units, "g_far", SH.BODY_KINDS) is None  # 別のページ
    assert SH.map_unit(LAYOUT, units, "g_missing", SH.BODY_KINDS) is None


def test_map_param_prefers_evidence_and_refuses_ambiguity():
    ix = PolicyIndex(PDOC)
    assert SH.map_param(ix, "30万円", ["p1"]) == "v002"  # 根拠の中で 1 つ（p2 の v003 ではない）
    assert SH.map_param(ix, "300,000円", ["p1"]) == "v002"  # 表記ではなく値で比べる
    assert SH.map_param(ix, "30万円", []) is None  # 文書全体では 2 つあって決められない
    assert SH.map_param(ix, "5日", []) == "v004"  # 文書全体で 1 つに決まる
    assert SH.map_param(ix, "7万円", ["p1"]) is None


def test_build_shot_maps_rule():
    s = SH.build_doc_shot("doc-x--style", PDOC, LAYOUT, _spec([PAY], PARAMS), {})
    assert s.kept == ["pay_amount"] and not s.dropped
    steps = s.d_shot["answer"]["rules"][0]["steps"]
    assert steps[0]["expr"]["args"][1] == {"param": "v001"} and steps[1]["expr"]["args"][1] == {
        "param": "v002"
    }
    cards = json.loads(s.d_shot["problem"]["CARDS"])
    assert cards[0]["function"] == "pay_amount"
    assert [r["function"] for r in s.k_shot["rules"]] == ["pay_amount"]


def test_yakkan_constants_come_from_policy_constants():
    params = {k: {"from_const": k, "source": v["source"], "unit": "JPY"} for k, v in PARAMS.items()}
    s = SH.build_doc_shot(
        "doc-x--style", PDOC, LAYOUT, _spec([PAY], params), {"ded": "1万円", "lim": "30万円"}
    )
    assert s.kept == ["pay_amount"]


def test_unmappable_rule_and_its_dependents_are_dropped():
    bad = json.loads(json.dumps(PAY).replace('"lim"', '"missing"'))
    uses = _rule(
        "uses_pay",
        [{"name": "o", "expr": {"op": "add", "args": [{"rule": "pay_amount"}, {"lit": 1}]}}],
        "o",
        ["g_p1"],
    )
    s = SH.build_doc_shot("doc-x--style", PDOC, LAYOUT, _spec([bad, uses], PARAMS), {})
    assert s.kept == [] and s.d_shot is None
    assert "写せない" in s.dropped["pay_amount"] and "参照する" in s.dropped["uses_pay"]


def test_rule_without_mappable_evidence_is_dropped():
    far = json.loads(json.dumps(PAY).replace('"g_p1"]', '"g_far"]'))
    far["sources"] = [{"unit": "g_far"}]
    s = SH.build_doc_shot("doc-x--style", PDOC, LAYOUT, _spec([far], PARAMS), {})
    assert s.dropped == {"pay_amount": "根拠の単位を pdoc に写せない"}


def test_rename_clashes_with_pilot_names():
    s = SH.build_doc_shot("doc-x--style", PDOC, LAYOUT, _spec([PAY], PARAMS), {})
    ren = SH.rename_clashes([s], {"pay_amount", "other"})
    assert ren == {"pay_amount": "example_fn_01"} and s.renamed == ren
    blob = json.dumps([s.d_shot, s.k_shot], ensure_ascii=False)
    assert "pay_amount" not in blob and "example_fn_01" in blob
    SH.check_names_disjoint([s.d_shot], {"pay_amount"})  # 置き換えた後は重ならない
    with pytest.raises(SH.ShotsError):
        SH.check_names_disjoint([s.d_shot], {"example_fn_01"})


def test_write_and_load(tmp_path):
    s = SH.build_doc_shot("doc-x--style", PDOC, LAYOUT, _spec([PAY], PARAMS), {})
    rep = SH.write_shots("yakkan", [s], tmp_path)
    assert rep["docs"][0]["kept"] == ["pay_amount"]
    assert PS.load("yakkan", "d_spec", tmp_path)[0]["doc_id"] == "doc-x--style"
    assert PS.load("yakkan", "k_cards", tmp_path)[0]["rules"][0]["function"] == "pay_amount"
    with pytest.raises(PS.ShotsMissing, match="make-shots"):
        PS.load("contract", "d_spec", tmp_path)
    with pytest.raises(SH.ShotsError):
        SH.write_shots("contract", [SH.DocShot("e--s")], tmp_path)

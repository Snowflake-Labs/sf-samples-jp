"""読み取りの採点（評価側）：恒等の逆対照・対応しない場合・1 対 1・体裁の照合・layout.json の場所。"""

from __future__ import annotations

from pathlib import Path

import pytest

from jpcalc.config import load_corpus_config
from jpcalc.eval.read_score import ReadScoreError, layout_path, score


def _pdoc(units):
    """units: [(kind, page, bbox)] から pdoc の最小形を作る。表・算式・図は、最初の条のブロックに付ける。"""
    body, blocks = [], []
    for kind, page, bbox in units:
        src = [{"page": page, "line": 0, "bbox": bbox}]
        if kind in ("table", "formula", "figure"):
            blocks.append({"type": kind, "page": page, "bbox": bbox})
        else:
            body.append({"kind": kind, "src": src, "children": [], "blocks": []})
    art = next((n for n in body if n["kind"] == "article"), None)
    if art is None:
        art = {"kind": "section", "src": [], "children": [], "blocks": []}
        body.append(art)
    art["blocks"] = blocks
    return {"body": body}


def _layout(units, style="s1"):
    kinds = {"formula": "formula_box"}
    return {
        "style_id": style,
        "elements": {
            f"e{i}": {
                "kind": kinds.get(k, k),
                "fragments": [{"page": p, "bbox": b, "repeated": False}],
            }
            for i, (k, p, b) in enumerate(units)
        },
    }


UNITS = [
    ("chapter", 1, [40, 50, 300, 62]),
    ("article", 1, [40, 70, 300, 82]),
    ("paragraph", 1, [40, 90, 500, 120]),
    ("item", 1, [60, 130, 500, 150]),
    ("table", 2, [40, 100, 400, 200]),
    ("formula", 2, [40, 220, 400, 250]),
    ("figure", 2, [40, 300, 400, 500]),
]


def test_identity_matches_all():
    # 逆対照：pdoc と同じ位置の正解は、すべての種類で再現率・適合率とも 1
    s = score("d--s1", _pdoc(UNITS), _layout(UNITS))
    for k, v in s.kinds.items():
        assert (v.n_gold, v.n_match) == (v.n_pred, v.n_pred), k
        assert v.recall == 1.0 and v.precision == 1.0, k


def test_other_page_or_far_box_does_not_match():
    gold = [("article", 2, [40, 70, 300, 82]), ("article", 1, [40, 600, 300, 612])]
    s = score("d--s1", _pdoc([("article", 1, [40, 70, 300, 82])]), _layout(gold))
    assert s.kinds["article"].n_match == 0 and s.kinds["article"].recall == 0.0


def test_one_to_one():
    # 正解 1 つに pdoc の単位が 2 つ重なっても、対応は 1 つ
    pred = [("paragraph", 1, [40, 90, 500, 100]), ("paragraph", 1, [40, 105, 500, 118])]
    s = score("d--s1", _pdoc(pred), _layout([("paragraph", 1, [40, 88, 500, 120])]))
    assert s.kinds["paragraph"].n_match == 1 and s.kinds["paragraph"].precision == 0.5


def test_body_merges_paragraph_and_item():
    # 正解が号、読み取りが項と組んだ単位も、本文の単位では対応する
    s = score(
        "d--s1",
        _pdoc([("paragraph", 1, [60, 130, 500, 150])]),
        _layout([("item", 1, [60, 130, 500, 150])]),
    )
    assert s.kinds["item"].n_match == 0 and s.kinds["body"].n_match == 1


def test_style_mismatch_is_refused():
    with pytest.raises(ReadScoreError, match="体裁"):
        score("d--s2", _pdoc(UNITS), _layout(UNITS, style="s1"))


def test_layout_path():
    root = Path("/eval")
    y = layout_path(load_corpus_config("yakkan"), root, "xxx-0001-c1--sty-a")
    assert y == root / "documents/xxx-0001-c1/xxx-0001-c1--sty-a/layout.json"
    c = layout_path(load_corpus_config("contract"), root, "xxx-0002--sty-b")
    assert c == root / "inputs/xxx-0002/layout.json"


def test_pdf_id_without_style_is_refused():
    with pytest.raises(ReadScoreError, match="体裁"):
        layout_path(load_corpus_config("contract"), Path("/eval"), "xxx-0002")

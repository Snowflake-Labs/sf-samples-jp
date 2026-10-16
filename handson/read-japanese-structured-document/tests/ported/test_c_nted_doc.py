"""文書順の nTED（C-012・T11.1）の試験。

オラクル（gold の木を文書順の outline にしたもの）で 0、空の予測で 1、条を入れ替えると > 0、
`elements.jsonl` の行順を乱しても値が変わらないこと。既存の `nted` は行順に依存する（だから足した）ことも確かめる。
"""

import json
import random

import pytest
from fixtures.data_roots import CDOCS, SKIP_REASON

DOC = "lea-0004--ct-a4-1col-form"  # 条が 10 以上あり、行順と文書順が食い違う

needs_docs = pytest.mark.skipif(not (CDOCS and (CDOCS / DOC).exists()), reason=SKIP_REASON)


@pytest.fixture
def mods(monkeypatch):
    from jpdocread.eval import evaluate, gold, metrics_order, metrics_structure

    monkeypatch.setattr(gold, "doc_dir", lambda d: CDOCS / d)
    gold.load_layout.cache_clear()
    return evaluate, gold, metrics_order, metrics_structure


def _gold_els():
    return [
        json.loads(x)
        for x in (CDOCS / DOC / "elements.jsonl").read_text("utf-8").splitlines()
        if x.strip()
    ]


def _oracle_outline(mo, els):
    """gold の木を文書順に並べた outline（予測の形）。"""
    rank = mo.gold_reading_rank(DOC)
    els = [e for e in els if e.get("node_kind")]
    ids = {e["element_id"] for e in els}
    kids: dict = {}
    for e in els:
        kids.setdefault(e.get("parent_id") if e.get("parent_id") in ids else None, []).append(e)
    memo: dict = {}

    def pos(e):
        if e["element_id"] not in memo:
            memo[e["element_id"]] = min(
                [rank.get(e["element_id"], 10**9)] + [pos(c) for c in kids.get(e["element_id"], [])]
            )
        return memo[e["element_id"]]

    out = []

    def walk(pid):
        for e in sorted(kids.get(pid, []), key=pos):
            out.append(
                {
                    "id": e["element_id"],
                    "node_kind": e["node_kind"],
                    "label": e.get("label") or "",
                    "parent_id": e.get("parent_id") if e.get("parent_id") in ids else None,
                }
            )
            walk(e["element_id"])

    walk(None)
    return out


@needs_docs
def test_oracle_is_zero_and_empty_is_one(mods):
    ev, _, mo, _ = mods
    outline = _oracle_outline(mo, _gold_els())
    r = mo.nted_doc(DOC, ev.tree_from_outline(DOC, {"outline": outline}))
    assert r["ted_doc"] == 0 and r["nted_doc"] == 0.0 and r["n_unordered"] == 0
    empty = mo.nted_doc(DOC, ev.tree_from_outline(DOC, {"outline": []}))
    assert empty["nted_doc"] == pytest.approx(1.0, abs=0.01)  # 仮想根ぶん N/(N+1)


@needs_docs
def test_old_nted_penalizes_the_correct_tree(mods):
    """既存の `nted` は gold の行順（id の文字列順）で比べるので、正しい木でも 0 にならない。"""
    ev, _, mo, ms = mods
    outline = _oracle_outline(mo, _gold_els())
    assert ms.nted(DOC, ev.tree_from_outline(DOC, {"outline": outline}))["nted"] > 0.3


@needs_docs
def test_swapping_articles_is_penalized(mods):
    ev, _, mo, _ = mods
    outline = _oracle_outline(mo, _gold_els())
    arts = [i for i, o in enumerate(outline) if o["node_kind"] == "article"]
    a, b = arts[0], arts[1]
    swapped = outline[:a] + outline[b : arts[2]] + outline[a:b] + outline[arts[2] :]
    assert mo.nted_doc(DOC, ev.tree_from_outline(DOC, {"outline": swapped}))["ted_doc"] > 0


@needs_docs
def test_invariant_to_elements_line_order(mods, monkeypatch):
    ev, gold, mo, _ = mods
    els = _gold_els()
    outline = _oracle_outline(mo, els)
    tree = ev.tree_from_outline(DOC, {"outline": outline})
    base = mo.nted_doc(DOC, tree)["ted_doc"]
    shuffled = els[:]
    random.Random(7).shuffle(shuffled)
    monkeypatch.setattr(mo, "load_elements", lambda d: shuffled)
    assert mo.nted_doc(DOC, tree)["ted_doc"] == base == 0


def test_containers_take_min_descendant_position(monkeypatch):
    """reading_order に現れない入れ物（pre・sig など）は子孫の最小位置に置く。"""
    from jpdocread.eval import metrics_order as mo

    els = [
        {"element_id": "sig", "node_kind": "signature", "label": "", "parent_id": None},
        {"element_id": "sig_p1", "node_kind": "paragraph", "label": "", "parent_id": "sig"},
        {"element_id": "a1", "node_kind": "article", "label": "第1条", "parent_id": None},
        {"element_id": "pre", "node_kind": "preamble", "label": "", "parent_id": None},
        {"element_id": "pre_p1", "node_kind": "paragraph", "label": "", "parent_id": "pre"},
    ]
    monkeypatch.setattr(mo, "load_elements", lambda d: els)
    monkeypatch.setattr(
        mo,
        "load_layout",
        lambda d: {"pages": [{"reading_order": ["pre_p1", "a1"]}, {"reading_order": ["sig_p1"]}]},
    )
    t, n_un = mo.gold_labeled_tree_doc("x")
    roots_in_postorder = [lab for lab in t.labels if lab[0] in ("preamble", "article", "signature")]
    assert (
        roots_in_postorder == [("preamble", ""), ("article", "第1条"), ("signature", "")]
        and n_un == 0
    )


# ---------------------------------------------------------------- 予測側：2 段組の分割点（T11.4）


def _w(x0, x1, top, text):
    return {"x0": x0, "x1": x1, "top": top, "bottom": top + 10, "text": text}


def test_snap_gutter_keeps_full_left_column_line_in_left():
    """左段いっぱいの行（x1=578）は、文書 gutter（566）が左にずれていても左段に置く（pur-0004 の形）。"""
    from jpdocread.read.geometry import lines_in_reading_order

    words = [
        _w(609, 875, 44, "右段の先頭"),
        _w(45, 291, 52, "買主"),
        _w(40, 578, 92, "前文（左段いっぱい）"),
        _w(40, 389, 106, "前文の続き"),
        _w(609, 867, 98, "右段の二行目"),
    ]
    words += [_w(40, 500, 120 + 14 * i, f"左{i}") for i in range(5)] + [
        _w(609, 900, 120 + 14 * i, f"右{i}") for i in range(5)
    ]
    old, _, _ = lines_in_reading_order(words, 1190, 842, gutter=566.0)
    new, g, n = lines_in_reading_order(words, 1190, 842, gutter=566.0, snap_gutter=True)
    first = lambda ls: [ln[0]["text"] for ln in ls][:4]  # noqa: E731
    assert first(old).index("右段の先頭") < first(old).index(
        "前文（左段いっぱい）"
    )  # 従来：前文の前に右段が割り込む
    assert (
        first(new) == ["買主", "前文（左段いっぱい）", "前文の続き", "左0"] and n == 2 and g == 607
    )


def test_snap_gutter_still_treats_true_spanning_line_as_spanning():
    """右段の行頭を越える本当の全幅行（題名など）は従来どおりゾーンを区切る（否定例）。"""
    from jpdocread.read.geometry import lines_in_reading_order

    words = [_w(300, 900, 20, "全幅の題名")]
    words += [_w(40, 500, 60 + 14 * i, f"左{i}") for i in range(5)] + [
        _w(609, 900, 60 + 14 * i, f"右{i}") for i in range(5)
    ]
    new, _, n = lines_in_reading_order(words, 1190, 842, gutter=566.0, snap_gutter=True)
    assert [ln[0]["text"] for ln in new][:2] == ["全幅の題名", "左0"] and n == 2


def test_parent_cycle_does_not_recurse_forever(monkeypatch):
    from jpdocread.eval import metrics_order as mo

    els = [
        {"element_id": "a", "node_kind": "article", "label": "第1条", "parent_id": "b"},
        {"element_id": "b", "node_kind": "paragraph", "label": "", "parent_id": "a"},
    ]
    monkeypatch.setattr(mo, "load_elements", lambda d: els)
    monkeypatch.setattr(mo, "load_layout", lambda d: {"pages": [{"reading_order": ["a"]}]})
    mo.gold_labeled_tree_doc("x")  # 例外にならない

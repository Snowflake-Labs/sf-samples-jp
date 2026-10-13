"""当事者・定義語の採点（T6.2・C-007）と契約書の条項木（T3.1・T3.2・C-006）の試験。

採点：オラクル（gold から作った予測）で 1.0、空の予測で 0、呼称の取り違えを数える。
規則：正規表現は肯定例と否定例（本文中の参照）を対で持つ。
"""

import json

import pytest
from fixtures.data_roots import CDOCS, SKIP_REASON

DOC = "sys-0004--ct-a4-1col-mincho"

needs_docs = pytest.mark.skipif(not (CDOCS and (CDOCS / DOC).exists()), reason=SKIP_REASON)


@pytest.fixture
def ev(monkeypatch):
    from jpdocread.eval import contract_semantics as cs
    from jpdocread.eval import gold

    monkeypatch.setattr(gold, "doc_dir", lambda d: CDOCS / d)
    gold.load_source.cache_clear()
    monkeypatch.setattr(
        cs, "load_source", lambda d: json.loads((CDOCS / d / "source.json").read_text("utf-8"))
    )
    return cs


@needs_docs
def test_oracle_scores_one_and_empty_scores_zero(ev):
    src = json.loads((CDOCS / DOC / "source.json").read_text("utf-8"))
    oracle = {
        "parties": [{"alias": p["alias"], "name": p["name"]} for p in src["meta"]["parties"]],
        "defined_terms": [t["term"] for t in src["defined_terms"]],
    }
    assert ev.party_scores(DOC, oracle)["f1"] == 1.0
    assert ev.term_scores(DOC, oracle)["f1"] == 1.0
    assert ev.party_scores(DOC, {})["f1"] == 0.0 and ev.term_scores(DOC, {})["f1"] == 0.0


@needs_docs
def test_alias_swap_is_counted_and_width_is_normalized(ev):
    src = json.loads((CDOCS / DOC / "source.json").read_text("utf-8"))
    a, b = src["meta"]["parties"][:2]
    swapped = {
        "parties": [
            {"alias": b["alias"], "name": a["name"]},
            {"alias": a["alias"], "name": b["name"]},
        ]
    }
    s = ev.party_scores(DOC, swapped)
    assert s["tp"] == 0 and s["n_alias_swapped"] == 2
    spaced = {
        "parties": [{"alias": a["alias"], "name": a["name"].replace("株式会社", "株式会社　")}]
    }
    assert ev.party_scores(DOC, spaced)["tp"] == 1


def test_summarize_is_micro_and_skips_docs_without_gold(ev):
    rows = [
        {"n_gold": 2, "n_pred": 2, "tp": 2},
        {"n_gold": 0, "n_pred": 3, "tp": 0},
        {"n_gold": 2, "n_pred": 1, "tp": 0},
    ]
    s = ev.summarize(rows)
    assert s["n_docs"] == 2 and s["recall"] == 0.5 and s["precision"] == round(2 / 3, 4)


# ---------------------------------------------------------------- 規則（予測側）


def _build(lines: list[str], scheme: str):
    from jpdocread.read.structure.contract import build_contract_tree

    return build_contract_tree("t", {1: "\n".join(lines)}, scheme)


def _cits(tree, kind):
    return [n.citation for n in tree.nodes.values() if n.kind == kind]


PRE = "株式会社アオ（以下「甲」という。）と株式会社キイ（以下「乙」という。）とは、次のとおり契約する。"


def test_detect_scheme_positive_and_negative():
    from jpdocread.read.structure.contract import detect_contract_scheme as det

    assert det([PRE, "第１条（目的）", "本文。", "第２条（定義）"]) == "contract-standard"
    assert (
        det(
            [
                PRE,
                "（総則）",
                "第一条甲は…",
                "（定義）",
                "第二条この…",
                "（譲渡）",
                "第三条当事者は…",
            ]
        )
        == "contract-kanji"
    )
    assert (
        det(
            [
                "事業主有限会社アオ",
                "労働者青木一郎",
                "①事業主は…",
                "１用語",
                "（１）用語",
                "①本書…",
                "②表…",
            ]
        )
        == "contract-form"
    )
    # 約款（当事者の宣言も当事者欄も無い）は None
    assert det(["第１章　総則", "第１条（用語の定義）", "この約款において…"]) is None


def test_items_are_children_of_paragraphs_and_cite_paragraph_label():
    t = _build(
        [
            PRE,
            "第３条（定義）",
            "次に掲げる用語の意味は次のとおりとする。",
            "（１）本件とは、Ａをいう。",
            "（２）委託とは、Ｂをいう。",
            "２乙は、次に掲げる行為をしてはならない。",
            "（１）開示すること",
        ],
        "contract-standard",
    )
    assert _cits(t, "item") == ["第３条 （１）", "第３条 （２）", "第３条 ２ （１）"]
    assert _cits(t, "paragraph") == ["", "第３条", "第３条 ２"]  # 前文の段落は引用が空


def test_reference_at_line_head_does_not_open_paragraph_or_item():
    t = _build(
        [
            PRE,
            "第５条（解除）",
            "甲は、次の場合に解除できる。ただし、",
            "２の規定にかかわらず、乙は…",
            "（１）の書類を出さないとき",
        ],
        "contract-standard",
    )
    assert _cits(t, "paragraph") == ["", "第５条"] and _cits(t, "item") == []


def test_month_amount_is_paragraph_but_date_is_not():
    t = _build(
        [PRE, "第５条（報酬）", "甲は報酬を支払う。", "2月額報酬の対象は…", "3月1日までに支払う。"],
        "contract-standard",
    )
    assert _cits(t, "paragraph") == ["", "第５条", "第５条 2"]


def test_kanji_article_needs_title_line_and_keeps_kanji_label():
    t = _build(
        [PRE, "（総則）", "第一条甲および乙は…", "2乙は…", "第二十一条の規定により…"],
        "contract-kanji",
    )
    assert _cits(t, "article") == ["第一条"]
    assert _cits(t, "paragraph") == ["", "第一条", "第一条 2"]


def test_form_scheme_chapter_article_paragraph_item():
    t = _build(
        [
            "事業主有限会社アオ",
            "労働者青木一郎",
            "①事業主は、労働者に下記のとおり示す。",
            "１用語の意味",
            "（１）用語",
            "①本書の用語は表１による。",
            "５休日",
            "（１）休日",
            "①休日は次のとおり。",
            "ｱ毎週日曜日",
            "ｲ祝日",
        ],
        "contract-form",
    )
    assert _cits(t, "chapter") == ["１", "５"] or _cits(t, "chapter") == ["１"]
    assert "１ （１） ①" in _cits(t, "paragraph")
    assert _cits(t, "paragraph")[0] == "①"  # 様式型の前文は ① ラベル付き


def test_titled_items_move_under_article_with_body_paragraph():
    t = _build(
        [
            PRE,
            "第３条（業務の範囲）",
            "本件業務の範囲は、次に掲げるとおりとする。",
            "（１）図面の作成",
            "甲の仕様に基づき図面を作る。",
            "（２）図面の点検",
            "図面を確かめる。",
            "２乙は…",
        ],
        "contract-standard",
    )
    items = [n for n in t.nodes.values() if n.kind == "item"]
    assert [i.citation for i in items] == ["第３条 （１）", "第３条 （２）"]
    assert all(t.nodes[i.parent_id].kind == "article" for i in items)
    assert [t.nodes[c].citation for i in items for c in i.children] == [
        "第３条 （１）",
        "第３条 （２）",
    ]


def test_signature_and_appendix():
    t = _build(
        [
            PRE,
            "第１条（目的）",
            "本文。",
            "本契約の成立を証するため、本書２通を作成する。",
            "２０２８年５月１０日",
            "別紙１作業の分担",
            "１分担は表１のとおり。",
            "２記号は…",
        ],
        "contract-standard",
    )
    assert _cits(t, "signature") == [""] and _cits(t, "appendix") == ["別紙１"]
    assert _cits(t, "paragraph")[-2:] == ["別紙１ １", "別紙１ ２"]


def test_parties_and_terms_from_text():
    from jpdocread.read.parties import defined_terms, parties

    t = _build(
        [
            "委託者株式会社アオ",
            "受託者株式会社キイ",
            PRE,
            "第２条（定義）",
            "用語の意義は次のとおり。",
            "（１）本件仕組みとは、甲が用いる仕組みをいう。",
            "２本契約において「営業日」とは、休業日を除いた日をいう。",
        ],
        "contract-standard",
    )
    ps = parties(t, ["委託者株式会社アオ", "受託者株式会社キイ"])
    assert [(p["alias"], p["name"], p["role"]) for p in ps] == [
        ("甲", "株式会社アオ", "委託者"),
        ("乙", "株式会社キイ", "受託者"),
    ]
    assert {d["term"] for d in defined_terms(t)} == {"本件仕組み", "営業日"}


def test_non_party_declaration_is_not_a_party():
    from jpdocread.read.parties import parties

    t = _build(
        [
            "甲と乙とは、基本契約（以下「本契約」という。）を締結する。株式会社アオ（以下「甲」という。）",
            "第１条（目的）",
            "本文。",
        ],
        "contract-standard",
    )
    assert [p["alias"] for p in parties(t, [])] == ["甲"]

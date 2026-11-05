"""段 A：合成 PDF から pdoc を組む（条・項・号・算式・表・囲み・図・値スパン・読み取りの失敗）。"""

from __future__ import annotations

import json

import pytest
from fixtures.synthetic_pdf import (
    Page,
    Text,
    build_pdf,
    contract_kanji_pages,
    contract_pages,
    yakkan_pages,
)

from jpcalc.pdfread.pdoc import SCHEMA, build


def _nodes(ns):
    for n in ns:
        yield n
        yield from _nodes(n.get("children", []))


def _blocks(doc):
    return [b for n in _nodes(doc["body"]) for b in n.get("blocks", [])]


@pytest.fixture(scope="module")
def yakkan(tmp_path_factory):
    return build("y", build_pdf(tmp_path_factory.mktemp("y") / "y.pdf", yakkan_pages()))


@pytest.fixture(scope="module")
def contract(tmp_path_factory):
    return build("c", build_pdf(tmp_path_factory.mktemp("c") / "c.pdf", contract_pages()))


def test_shape(yakkan):
    assert yakkan["schema_version"] == SCHEMA
    assert yakkan["content_id"] == "y"
    p = yakkan["pdoc"]
    assert p["pdf_id"] == "y" and p["scheme"] is None
    assert p["read_errors"] == [] and p["value_span_errors"] == []


def test_articles_paragraphs_items(yakkan):
    arts = [n for n in yakkan["body"] if n["kind"] == "article"]
    assert [(a["label"], a["title"]) for a in arts] == [
        ("第１条", "保険金を支払う場合"),
        ("第２条", "保険金の額"),
        ("第３条", "保険金を支払わない場合"),
    ]
    a2 = [c["label"] for c in arts[1]["children"]]
    assert a2 == ["", "２．"]  # 第 1 項は番号なし
    a3 = [c["label"] for c in arts[2]["children"]]
    assert a3 == ["", "（１）", "（２）"]
    # 出所（ページ・bbox）
    assert arts[0]["src"][0]["page"] == 2 and len(arts[0]["src"][0]["bbox"]) == 4


def test_verbatim_text(yakkan):
    texts = [n.get("text", "") for n in _nodes(yakkan["body"])]
    # NFKC にしない：全角の括弧・数字がそのまま残る
    assert "故意によって生じた損害" in texts
    assert any("別表１の支払限度額" in t for t in texts)
    assert not any("別表1" in t for t in texts)


def test_value_spans(yakkan):
    consts = yakkan["meta"]["constants"]
    assert sorted(consts.values()) == ["１０万円", "３万円", "７万円"]  # 原文の表記のまま
    box = next(b for b in _blocks(yakkan) if b["type"] == "box")
    text = box["blocks"][0]["text"]
    assert "{const:" in text and "１０万円" not in text


def test_formula(yakkan):
    fml = [b for b in _blocks(yakkan) if b["type"] == "formula"]
    assert len(fml) == 1
    terms = fml[0]["terms"][0]["text"]
    assert terms.startswith("損害の額－免責金額{const:") and terms.endswith("＝保険金の額")


def test_table(yakkan):
    tbl = next(b for b in _blocks(yakkan) if b["type"] == "table")
    grid = [[c["text"] for c in row] for row in tbl["grid"]]
    assert grid == [["区分", "支払限度額"], ["Ａ型", "１００万円"], ["Ｂ型", "２００万円"]]


def test_box_and_figure(yakkan):
    box = next(b for b in _blocks(yakkan) if b["type"] == "box")
    assert box["blocks"][0]["text"].startswith("（設例）")
    fig = next(b for b in _blocks(yakkan) if b["type"] == "figure")
    assert fig["caption"] == "保険金の請求の流れ"
    labels = [n["label"] for n in fig["diagram"]["nodes"]]
    assert labels == ["事故の発生", "保険金の請求"]
    assert fig["diagram"]["edges"] == [{"from": "n0", "to": "n1", "label": None}]
    assert fig["facts"] == ["「事故の発生」から「保険金の請求」に進む。"]


def test_contract(contract):
    p = contract["pdoc"]
    assert p["scheme"] == "contract-standard" and p["read_errors"] == []
    arts = contract["body"]
    assert [a["title"] for a in arts] == ["委託料", "遅延損害金", "検収"]
    # 契約書の項の番号（「２甲は、…」）
    assert [c["label"] for c in arts[0]["children"]] == ["", "２"]
    assert arts[0]["children"][1]["text"].startswith("甲は、毎月末日締めで")
    assert sorted(contract["meta"]["constants"].values()) == [
        "１０営業日",
        "１４．６％",
        "５０万円",
    ]


def test_deterministic(tmp_path):
    a = build("y", build_pdf(tmp_path / "a.pdf", yakkan_pages()))
    b = build("y", build_pdf(tmp_path / "b.pdf", yakkan_pages()))
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(
        b, ensure_ascii=False, sort_keys=True
    )


def test_read_failure_is_recorded(tmp_path):
    # 逆対照：見出しが太字でない（見出しを読めない）PDF は本文が空になり、それを read_errors に残す
    page = Page(
        texts=[Text(60, 780 - 18 * i, s) for i, s in enumerate(["第１条（見本）", "本文です。"])]
    )
    d = build("x", build_pdf(tmp_path / "x.pdf", [page]))
    assert d["body"] == []
    assert [e["error"] for e in d["pdoc"]["read_errors"]] == [
        "本文の見出し（条など）を 1 つも読めず、本文が空になった"
    ]


def test_contract_kanji_articles(tmp_path):
    """漢数字の条（題名の行の次の「第一条…」）を条として読む。本文中の「第三条に定める」は条にしない。"""
    d = build("k", build_pdf(tmp_path / "k.pdf", contract_kanji_pages()))
    p = d["pdoc"]
    assert p["scheme"] == "contract-kanji" and p["read_errors"] == []
    arts = [n for n in d["body"] if n["kind"] == "article"]
    assert [(a["label"], a["title"]) for a in arts] == [
        ("第一条", "総則"),
        ("第二条", "請負代金"),
        ("第三条", "検査"),
        ("第三条の二", "再委託"),
        ("第四条", "解除"),
    ]
    # 参照の行は第二条の本文に残る
    text2 = "".join(x.get("text", "") for x in _nodes(arts[1]["children"]))
    assert "第三条に定める検査の後" in text2

"""W13 — 容器（`別表`/`付表`・`附則`）の同定（T44 / T45）。

**容器 1 件の誤りは配下の全段落の引用を壊す。** 実測（ALL 39）では容器ノードの欠落が
合計 27 件しかないのに、段落の誤接続 180 件を生んでいた（約 7 倍の増幅）。

| 規則 | 何が壊れていたか | 実測 |
|---|---|---|
| `RE_APPENDIX` の参照除外（T44） | **否定規則を 1 つも通していなかった**ので本文中の参照が容器を開いた | `section` R 0.8814 → 0.9492・条 R 0.9553 → 0.9639 |
| `RE_TOC_ENTRY` に `附則`（T45） | 語彙の穴。目次の `附則11` が落ちず p2 で容器が開き、本文 p11 が `_dup` に吸収された | `appendix_section` R 0.8571 → 0.9740 |
"""

from __future__ import annotations

from jpdocread.read.structure.lines import RE_TOC_ENTRY, is_toc_line
from jpdocread.read.structure.tree import build_tree, canonical_citation


class TestAppendixReferenceIsNotAContainer:
    """T44。**否定例は本文中の参照である**。"""

    def test_reference_to_a_table_does_not_open_a_container(self):
        """`auto-0001-b5` p12 の実物。**この 1 行が `第5章 第3節`〜`第6節` を潰していた。**"""
        pages = {
            1: "第1章総則\n第1条（用語の定義）\n本文である。\n"
            "付表1に定める短期率により計算した既経過期間\n"
        }
        t = build_tree("r_app_ref", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "appendix"] == []
        assert any("参照（別表/付表）" in r for r in t.rejected)

    def test_prose_reference_ending_in_a_period_is_not_a_container(self):
        """`life-0001-b5` と `travel-0002` の実物。`_is_prose`（句点）で落ちる側。"""
        for body in (
            "別表１に掲げる状態に該当されたときです。",
            "別表2に掲げる物は携行品に当たらないため、この表の対象になりません。",
        ):
            pages = {1: "第1章総則\n第1条（用語の定義）\n本文である。\n" + body + "\n"}
            t = build_tree("r_app_prose", pages)
            assert [n.label for n in t.nodes.values() if n.kind == "appendix"] == [], body

    def test_a_real_table_heading_still_opens(self):
        """肯定対：**本物の別表見出しは題名だけを伴う。** gold の 136 行はこの形。"""
        pages = {1: "別表1　後遺障害等級表\n第1　等級表\n1．第1級\n"}
        t = build_tree("r_app_ok", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "appendix"] == ["別表1"]

    def test_a_bare_table_label_still_opens(self):
        """肯定対：題名の無い `付表1` 単独行も容器である（`_is_prose('')` は偽）。"""
        pages = {1: "付表1\n第1　短期率表\n1．1か月\n"}
        t = build_tree("r_app_bare", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "appendix"] == ["付表1"]


class TestSupplementaryProvisionsInTocVocabulary:
    """T45。`附則` は**番号を持たない**ので、目次側と本文側は番号で区別できない。"""

    def test_toc_line_for_supplementary_provisions_is_recognised(self):
        """否定側：`附則11` は目次行である（末尾の 11 はページ番号）。"""
        assert RE_TOC_ENTRY.match("附則11") is not None
        assert is_toc_line("附則11")

    def test_body_heading_for_supplementary_provisions_is_not_a_toc_line(self):
        """肯定対：**本文の `附則` は裸のページ番号を持たない**ので落ちない。

        ここが分離の唯一の手掛かりである。`第N章` なら番号の連続性も使えるが、
        `附則` には番号が無い。
        """
        assert not is_toc_line("附則")
        assert not is_toc_line("附則　施行期日")

    def test_toc_supplementary_line_does_not_steal_the_body_container(self):
        """統合：目次の `附則11` が p1 にあっても、本文の `附則` 配下に節が生える。

        W12 T38 で観測した失敗は「p2 で `附則` が開き、本文 p11 が `_dup` に吸収され、
        配下の `第1`〜`第3` が容器を持てない」だった。
        """
        pages = {
            1: "もくじ\n第１章総則2\n附則11\n",
            2: "附則\n第１　施行期日\nこの定款は、令和8年4月1日から施行する。\n"
            "第２　経過措置\nなお従前の例による。\n",
        }
        t = build_tree("r_suppl", pages)
        cits = [
            canonical_citation(n.citation) for n in t.nodes.values() if n.kind == "appendix_section"
        ]
        assert "附則 第1" in cits
        assert "附則 第2" in cits
        apps = [n for n in t.nodes.values() if n.kind == "appendix"]
        assert [n.label for n in apps] == ["附則"]
        assert apps[0].pages == [2], "目次ページではなく本文ページで開くこと"

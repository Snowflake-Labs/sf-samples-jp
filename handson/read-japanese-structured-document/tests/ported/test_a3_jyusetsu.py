"""A3 — 版式推定と jyusetsu 文法（T11/T12）。

`jyusetsu` は約款ではない。`第N章`/`第N条` を使わないので約款用の正規表現は
**1 件も当たらず**、大域デコードも候補が無ければ働かない（実測 条 recall 0.000）。
"""

from __future__ import annotations

from jpdocread.read.structure.grammars import JYUSETSU, YAKKAN, infer_grammar, load_grammar
from jpdocread.read.structure.tree import build_tree


class TestGrammarInference:
    """**gold の `meta.numbering_scheme` は使えない**（§1.4 gold-blind）。印字形で決める。"""

    def test_jyusetsu_form_is_detected(self):
        lines = ["1用語のご説明", "(1)商品の仕組み"] + [f"{c}見出し" for c in "①②③④⑤⑥"]
        assert infer_grammar(lines) == JYUSETSU

    def test_yakkan_with_circled_paragraphs_is_not_jyusetsu(self):
        """否定例：group は項に丸数字を使う**約款**である。

        丸数字の多さだけで切り替えると、この体裁を jyusetsu と誤判定する。
        **条を 1 件も使っていないことを AND 条件にする**のが要点。
        """
        lines = ["第1章総則", "第1条当会社は、保険金を支払います。"] + [
            f"{c}前項の規定は適用しません。" for c in "①②③④⑤⑥⑦⑧"
        ]
        assert infer_grammar(lines) == YAKKAN

    def test_empty_document_defaults_to_yakkan(self):
        assert infer_grammar([]) == YAKKAN


class TestJyusetsuTree:
    def test_hierarchy_of_bare_paren_circled(self):
        """`1` → `(1)` → `①` → 散文。引用は gold の形（`2 (1) ①`）になる。"""
        pages = {
            1: "2契約締結前におけるご確認事項\n"
            "(1)商品の仕組み\n"
            "①この保険の型と補償の組み合わせ\n"
            "この保険は、四つの補償を組み合わせてご契約いただく自動車保険です。\n"
            "②主な補償の概要\n"
            "対人賠償および対物賠償は、いずれのタイプでも必ずセットされます。"
        }
        t = build_tree("j", pages, grammar=JYUSETSU)
        kinds = {n.kind: n for n in t.nodes.values()}
        assert kinds["chapter"].label == "2"
        assert kinds["section"].citation == "2 (1)"
        arts = [n for n in t.nodes.values() if n.kind == "article"]
        assert [a.citation for a in arts] == ["2 (1) ①", "2 (1) ②"]
        # 散文は無番号の段落になり、引用は条と同一（gold は 63 件すべて空ラベル）
        paras = [n for n in t.nodes.values() if n.kind == "paragraph"]
        assert [p.citation for p in paras] == ["2 (1) ①", "2 (1) ②"]

    def test_circled_restart_becomes_an_item_not_an_article(self):
        """**`article` と `item` は同じ丸数字。** 番号の単調性だけが区別する。

        ① ② ① ② ③ の並びで、3 番目の ① は条の期待値（③）と合わず 1 に戻って
        いるので条の下の細分である（gold `2 (2) ② ①`）。
        """
        pages = {
            1: "2ご確認事項\n(1)仕組み\n"
            "①最初の条\n本文です。\n"
            "②次の条\n本文です。\n"
            "①細分の一つめ\n"
            "②細分の二つめ\n"
            "③次の条の本体\n"
        }
        t = build_tree("j2", pages, grammar=JYUSETSU)
        arts = [n.citation for n in t.nodes.values() if n.kind == "article"]
        items = [n.citation for n in t.nodes.values() if n.kind == "item"]
        assert arts == ["2 (1) ①", "2 (1) ②", "2 (1) ③"]
        assert items == ["2 (1) ② ①", "2 (1) ② ②"]

    def test_toc_line_with_trailing_page_number_is_rejected(self):
        """否定例：`もくじ` は本文と同じ見出しを並べ、末尾にページ番号を置く。"""
        g = load_grammar(JYUSETSU)
        assert g.toc_entry.match("1用語のご説明2")
        assert g.toc_entry.match("①主な用語と略称2")
        assert g.toc_entry.match("(1)商品の仕組み3")
        # 本物の見出しは裸の数字で終わらない
        assert not g.toc_entry.match("(1)商品の仕組み")

    def test_prose_line_starting_with_a_digit_is_not_a_chapter(self):
        """否定例：`1億円を標準としています。` は本文。句読点で落とす。"""
        pages = {1: "2ご確認事項\n(1)仕組み\n①型\n1億円を標準としています。"}
        t = build_tree("j3", pages, grammar=JYUSETSU)
        assert [n.label for n in t.nodes.values() if n.kind == "chapter"] == ["2"]

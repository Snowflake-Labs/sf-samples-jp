"""T8：印刷目次を照合表として構築する。

**gold を目次の代用にしてはならない**（§1.4）。ここで固定するのは
「予測経路のテキストから目次が取れる」ことと、取れた表の形である。
"""

from __future__ import annotations

import pytest

from jpdocread.read.structure.toc import (
    RE_TOC_CITATION,
    RE_TOC_NUMBERED,
    build_toc,
    parse_toc_lines,
)


class TestTocForms:
    """目次には 2 形式ある。**どちらも取れること**を固定する。"""

    def test_page_form(self):
        e = parse_toc_lines([(2, "第１編ご契約のしおり4")])
        assert len(e) == 1
        assert (e[0].kind, e[0].num, e[0].title, e[0].page) == ("part", 1, "ご契約のしおり", 4)
        assert e[0].label == "第１編", "ラベルは逐語で保持する（§1.11：全角を畳まない）"
        assert e[0].form == "page"

    def test_citation_form(self):
        e = parse_toc_lines([(3, "保険金の請求第5章第4節第1条")])
        assert len(e) == 1
        assert e[0].kind == "article"
        assert (e[0].cit_chapter, e[0].cit_section, e[0].cit_article) == (5, 4, 1)
        assert e[0].page is None, "引用形式にページ番号は無い"
        assert e[0].form == "citation"

    def test_page_form_wins_over_citation(self):
        """`第1章総則2` は両方に一致しうる。**末尾が裸の数字ならページ形式。**"""
        e = parse_toc_lines([(2, "第1章総則2")])
        assert len(e) == 1
        assert e[0].form == "page" and e[0].page == 2

    def test_body_sentence_is_not_a_toc_entry(self):
        """句点を含む行は本文である。**否定例（§14：正規表現は肯定と否定を対で書く）。**"""
        assert parse_toc_lines([(5, "第5条（保険金の支払）の規定にかかわらず、当会社は…。")]) == []

    def test_long_body_fragment_is_not_a_citation_entry(self):
        """実測で拾われた誤検出。**長さで縛る**ので、これは目次項目にならない。"""
        line = "に残された機能の障害であって、その程度が別表１"
        assert RE_TOC_CITATION.match(line), "正規表現自体は一致する（だから長さ制約が要る）"
        assert parse_toc_lines([(4, line)]) == [], "句点または長さで落ちること"


class TestTocOnCorpus:
    def test_life_has_part_entries_with_pages(self):
        """`life` の編は目次にページ付きで載る。**T9 の編境界アンカーの前提。**"""
        t = build_toc("life-0001--life-a4-1col-gothic")
        parts = t.by_kind("part")
        assert len(parts) >= 2, f"編の目次項目が {len(parts)} 件。T9 のアンカーが立たない"
        assert all(p.page for p in parts)
        assert t.start_page("part", 2) is not None

    def test_auto_uses_citation_form(self):
        """`auto` はページ形式を持たない。**ページ形式だけの実装では 0 件になる。**"""
        t = build_toc("auto-0001--nl-a4-2col-mincho")
        assert t.has_toc, "auto の目次が取れていない（引用形式の実装漏れ）"
        assert all(e.form == "citation" for e in t.entries)

    def test_docs_without_toc_report_empty_not_error(self):
        """目次が無いことと読めなかったことを区別する。"""
        t = build_toc("golf-0001--nl-a4-2col-mincho")
        assert t.has_toc is False
        assert t.toc_pages == []

    @pytest.mark.parametrize(
        "doc_id",
        ["life-0001--life-a4-1col-gothic", "teikan-0001--teikan-a4-1col-mincho"],
    )
    def test_numbers_are_ints_for_constraints(self, doc_id):
        for e in build_toc(doc_id).entries:
            if e.kind in ("part", "chapter", "section", "article"):
                assert isinstance(e.num, int)


def test_regex_requires_trailing_number():
    """見出しだけの行（ページ番号なし）を目次にしない。"""
    assert RE_TOC_NUMBERED.match("第１編ご契約のしおり") is None


class TestOutlinePages:
    """T7 の実測で発覚した**第 3 の目次形式**（裸の見出し列）を固定する。"""

    def test_auto_page4_is_an_outline_page(self):
        """`auto-0001` p4 は見出しだけを並べた構成ページ。**本文ではない。**

        ここを本文として扱うと、載っている見出しが全部偽陽性になる
        （実測：候補 708 件・負例 114 件 → 除外後 566 件・負例 21 件）。
        """
        from jpdocread.read.structure.toc import build_toc

        t = build_toc("auto-0001--nl-a4-2col-mincho")
        assert 4 in t.outline_pages, "構成ページの検出が効いていない"

    def test_body_page_is_not_an_outline_page(self):
        """逆対照：本文ページを構成ページと誤判定しないこと。"""
        from jpdocread.read.structure.toc import build_toc

        t = build_toc("auto-0001--nl-a4-2col-mincho")
        assert 5 not in t.outline_pages
        assert 6 not in t.outline_pages


class TestCandidateScoring:
    """T7：候補スコア。**閾値で切るためではなく T9 に順序を与えるためのもの。**"""

    def test_reference_line_scores_low(self):
        """参照は最重要の減点対象（§5.6(4)）。"""
        from jpdocread.read.structure.candidates import candidates_for_doc

        cs = candidates_for_doc("auto-0001--nl-a4-2col-mincho")
        refs = [c for c in cs if "の算式は" in c.line]
        assert refs, "参照らしい行が候補に残っていない（却下してしまっている）"
        assert all(c.score < 0.5 for c in refs), "参照が高いスコアを得ている"

    def test_running_header_penalty_is_positional_not_textual(self):
        """柱の減点は**位置依存**でなければならない。

        文字列単位で一律に減点すると、同じ文字列を持つ**本物の見出しも罰する**
        （実測：正例の中央値が 2.00 → 0.08 に落ち、正例と負例が逆転した）。
        最初の出現は罰さず、2 回目以降だけ罰すること。
        """
        from jpdocread.read.structure.candidates import candidates_for_doc

        cs = candidates_for_doc("life-0001--life-a4-1col-gothic")
        rep = [c for c in cs if c.line == "第１編ご契約のしおり"]
        if len(rep) >= 2:
            first, rest = rep[0], rep[1:]
            assert all(c.feats["repeated_line"] == 1.0 for c in rest), "2 回目以降が罰されていない"
            assert first.feats["repeated_line"] == 0.0, "最初の出現を罰してはならない"

    def test_candidates_are_not_rejected(self):
        """**この層は却下しない。** 却下するとデコーダが選び直せない。"""
        from jpdocread.read.structure.candidates import candidates_for_doc

        cs = candidates_for_doc("auto-0001--nl-a4-2col-mincho")
        assert any(c.score < 0.5 for c in cs), "低スコアの候補が残っていない"
        assert any(c.score > 2.0 for c in cs)

    def test_toc_block_produces_no_candidates_but_the_body_on_the_page_does(self):
        """**抑止の単位はページではなく目次ブロックである（W8 で変更）。**

        以前この検査は「目次ページは候補を 1 つも出さない」を固定していた。
        **その契約が誤りだった。** 目次と本文が同居するページがあり、
        teikan の p2 は目次 9 行の後に本文の `第１章総則` と `第１条（商号）`〜が続く。
        ページ単位で飛ばすと本文見出しが候補に出ず、`heading_allow` に無いので
        組み立て側が本文化して **gold の `第1章 第1〜5条` を丸ごと落としていた。**

        実測（ALL 39 文書・`greedy`）：条 recall 0.8220 → **0.8478**、
        段落パス完全一致 0.7457 → **0.7744**、`item` recall 0.4294 → **0.5000**。
        """
        from jpdocread.read.structure.candidates import candidates_for_doc
        from jpdocread.read.structure.lines import RE_TOC_ENTRY
        from jpdocread.read.structure.toc import build_toc

        doc = "teikan-0001--teikan-a4-1col-mincho"
        t = build_toc(doc)
        skip = set(t.toc_pages) | set(t.outline_pages)
        on_toc_page = [c for c in candidates_for_doc(doc) if c.page in skip]

        # 目次行（末尾が裸のページ番号）からは候補が出ない。
        leaked = [c.line for c in on_toc_page if RE_TOC_ENTRY.match(c.line.strip())]
        assert leaked == [], f"目次行から候補が出ている: {leaked}"

        # **空振り防止：** 同じページの本文側からは候補が出る。
        # 出ていなければ、この検査はページ単位抑止のままでも通ってしまう。
        assert [c.line for c in on_toc_page] == [
            "第１章総則",
            "第１条（商号）",
            "第２条（目的）",
            "第３条（本店の所在地）",
        ]

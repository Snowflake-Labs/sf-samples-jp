"""W12 — 目次行の誤判定と、括弧見出しの後ろの参照（T35 / T36）。

どちらも**見かけは見出しだが見出しではない行**の問題である。規律は
「正規表現は 1 つずつ、肯定例と否定例を対で書く。否定例には必ず本文中の条項参照を
含める」と要求しているので、規則ごとに対で置く。

| 規則 | 何が壊れていたか | 実測 |
|---|---|---|
| `is_toc_line` | 段の右端で折り返し、たまたま数字で終わった本文行を目次行として落としていた | `item` 欠落 9 件の原因・段落 R 0.8989 → 0.9017 |
| 否定規則 1b | `第N条（題名）` の**後ろ**に参照規則を当てていなかった | 番号違反 intrinsic 13 → 7・条 P 0.9720 → 0.9737 |
"""

from __future__ import annotations

from jpdocread.read.structure.lines import TOC_NEGATIVE_MARKS, is_toc_line
from jpdocread.read.structure.tree import _after_paren_title, build_tree, canonical_citation


class TestTocLineNegativeRule:
    """`RE_TOC_ENTRY` は「見出しの形＋末尾の裸の数字」しか見ない。"""

    def test_wrapped_body_line_ending_in_a_digit_is_not_a_toc_line(self):
        """否定側：`group-0001` p6 の実物。**`item` 欠落 9 件すべての原因だった。**

        末尾の `5` は「5営業日」の 5 であってページ番号ではない。
        この行が落とされると `第7条` が開かず、配下の項と号が前条に吸収される。
        """
        s = "第7条保険金は、その請求に必要な書類が当会社に到着した日の翌営業日からその日を含めて5"
        assert not is_toc_line(s)

    def test_real_toc_entries_still_match(self):
        """肯定側：真の目次行は落ち続ける。ALL 39 の 527 行に `、` は 1 件も無い。"""
        assert is_toc_line("第1章総則2")
        assert is_toc_line("第６条（法令違反があったときの減額）7")
        assert is_toc_line("別表1後遺障害等級表15")
        assert is_toc_line("ゴルフ用具新価特約12")

    def test_a_heading_without_a_trailing_page_number_is_not_a_toc_line(self):
        """退化ケース：末尾に数字が無ければそもそも目次行ではない。"""
        assert not is_toc_line("第1条（用語の定義）")
        assert not is_toc_line("第1章総則")

    def test_dot_is_deliberately_excluded_from_the_negative_marks(self):
        """`1．` は号のラベル体裁なので `．` を否定記号に入れてはならない。

        入れると `1．総則5` のような目次行が落ちなくなる（実測 0 件だが、
        入れた瞬間に将来の版で静かに壊れる種になる）。
        """
        assert "．" not in TOC_NEGATIVE_MARKS
        assert "。" in TOC_NEGATIVE_MARKS
        assert "、" in TOC_NEGATIVE_MARKS


class TestAfterParenTitle:
    def test_returns_the_tail_after_the_matching_close(self):
        assert _after_paren_title("（機関）により置く取締役会は、…") == "により置く取締役会は、…"

    def test_nested_parens_are_counted(self):
        """最初の `）` で切ってはならない。約款の題名は入れ子になる。"""
        assert _after_paren_title("（保険金の請求（死亡の場合））") == ""
        assert _after_paren_title("（保険金の請求（死亡の場合））の規定により") == "の規定により"

    def test_not_starting_with_a_paren_is_not_a_target(self):
        """`第5条当会社は、…` の inline 体裁はこの判定の対象外である。"""
        assert _after_paren_title("当会社は、保険金を支払います。") == ""

    def test_unclosed_paren_is_not_a_target(self):
        assert _after_paren_title("（閉じていない題名") == ""


class TestReferenceAfterParenTitleIsNotAHeading:
    """否定規則 1b。**否定例は本文中の条項参照である**。"""

    def test_reference_with_a_paren_title_does_not_open_an_article(self):
        """`teikan-0001` の実物（`第4章 第5条: 20 → 5` の番号違反の原因）。

        番号が不連続（20 の次に 5）でも、`has_paren` が否定規則 2 を免除していた。
        """
        body = "第５条（機関）により置く取締役会は、法令に定める事項のほか、当会社の業務執行を決定する。"
        pages = {1: "第1章総則\n第1条（商号）\n当会社は、次のとおりとする。\n" + body + "\n"}
        t = build_tree("r_ref", pages)
        labels = [n.label for n in t.nodes.values() if n.kind == "article"]
        assert labels == ["第1条"]
        assert any("参照（括弧見出しの後）" in r for r in t.rejected)

    def test_reference_whose_tail_is_a_sentence_does_not_open_an_article(self):
        """`travel-0002` の実物（`第2条: 7 → 2`）。尾部が `の…。` で始まる。"""
        body = "第2条（入院保険金および通院保険金）の保険金を支払いません。ただし、重くなった部分は支払います。"
        pages = {
            1: "第1章総則\n第1条（用語の定義）\nこの約款において、次のとおりとする。\n"
            + body
            + "\n"
        }
        t = build_tree("r_ref2", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "article"] == ["第1条"]

    def test_a_real_article_heading_still_opens(self):
        """肯定対：**本物の条見出しは閉じ括弧で行が終わる。**"""
        pages = {
            1: "第1章総則\n第1条（用語の定義）\n本文である。\n第2条（保険金の支払）\n本文である。\n"
        }
        t = build_tree("r_ok", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "article"] == ["第1条", "第2条"]

    def test_inline_body_style_without_a_paren_title_still_opens(self):
        """肯定対：group の inline 体裁（句読点を含むが括弧題名が無い）は従来どおり開く。

        `第1条当会社は、…` は条＋**条ラベルを負う第一段落**に分かれる
        （gold の引用は `第1章 第1条 第1条`）。1b がこれを壊さないことを確かめる。

        **番号は連続させる。** `第5条` を `expect_article=1` の位置に置くと
        既存の否定規則 2（不連続かつ見出し無し）で落ち、1b の検証にならない。
        """
        pages = {
            1: "第1章総則\n第1条当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。\n"
        }
        t = build_tree("r_inline", pages)
        arts = [n for n in t.nodes.values() if n.kind == "article"]
        assert [n.label for n in arts] == ["第1条"]
        paras = [canonical_citation(n.citation) for n in t.nodes.values() if n.kind == "paragraph"]
        assert "第1章 第1条 第1条" in paras

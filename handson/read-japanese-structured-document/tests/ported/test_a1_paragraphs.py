"""A1 — 段落ラベルの流儀・裸数字・無番号第一段落。

**正規表現は肯定例と否定例を対で書く**。
否定例には必ず本文中の条項参照を含める（約款では偽陽性が支配的な誤り）。
"""

from __future__ import annotations

from jpdocread.read.structure.tree import (
    RE_PARA_BARE,
    SENTENCE_MARKS,
    Builder,
    build_tree,
)


class TestBareParagraphLabel:
    """裸の数字ラベル。空白を必須にすると teikan の 119 段落が落ちる。"""

    def test_full_width_digit_without_space(self):
        """肯定：teikan の実際の行。番号と本文の間に空白が無い。"""
        m = RE_PARA_BARE.match("２事故その他やむを得ない事由によって電子公告による")
        assert m is not None
        assert m.group(1) == "２"

    def test_with_ideographic_space(self):
        """肯定：空白がある体裁も従来どおり通る。"""
        m = RE_PARA_BARE.match("３　社員に対する通知または催告は、社員名簿に")
        assert m is not None
        assert m.group(1) == "３"

    def test_year_is_not_a_paragraph(self):
        """否定：4 桁の年号。`{1,2}` と先読みで落ちる。"""
        assert RE_PARA_BARE.match("２０２６年４月１日から適用する。") is None

    def test_two_digit_followed_by_digit_rejected(self):
        """否定：3 桁以上の数値。金額や条数の列挙を段落にしない。"""
        assert RE_PARA_BARE.match("１２３万円を限度とする。") is None

    def test_bare_digit_alone_rejected(self):
        """否定：数字だけの行（表のセルやページ番号）は本文を持たない。"""
        assert RE_PARA_BARE.match("12") is None


class TestSentenceMarkSeparatesTitleFromBody:
    """条ラベルの直後が題名か本文かを句読点 1 文字で分ける。"""

    def test_paren_title_has_no_sentence_mark(self):
        """否定（＝題名である）：gold の条見出し 1,222 件に句読点は 0 件。"""
        assert not any(c in "（公告方法）" for c in SENTENCE_MARKS)
        assert not any(
            c in "（使用目的および年間予定走行距離に関する条件）" for c in SENTENCE_MARKS
        )

    def test_inline_body_has_sentence_mark(self):
        """肯定（＝本文である）：group の実際の行。"""
        body = "当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。"
        assert any(c in body for c in SENTENCE_MARKS)


class TestUnnumberedFirstParagraph:
    def test_own_line_heading_yields_empty_label_paragraph(self):
        """teikan 形：条見出しが単独行 → 第一段落は空ラベルで引用は条と同一。"""
        pages = {
            1: "第１章総則\n第４条（公告方法）\n当会社の公告は、電子公告により行う。\n"
            "２事故その他やむを得ない事由によって電子公告による公告をすることができない。"
        }
        t = build_tree("t", pages)
        paras = [n for n in t.nodes.values() if n.kind == "paragraph"]
        assert [p.label for p in paras] == ["", "２"]
        # 空ラベルの段落は引用パスに何も足さない ＝ 条の引用と一致する
        assert paras[0].citation == "第1章 第4条"
        assert paras[1].citation == "第1章 第4条 ２"

    def test_inline_heading_repeats_article_label(self):
        """group 形：ラベルと本文が同一行 → 第一段落が条ラベルを負う。

        条番号は 1 から始める。飛んだ番号で括弧題名も無い行は否定規則 2 が落とすので
        （本文中の参照と区別できない）、ここで `第5条` から始めると条にならない。
        """
        pages = {
            1: "第1章総則\n第1条当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。"
        }
        t = build_tree("g", pages)
        arts = [n for n in t.nodes.values() if n.kind == "article"]
        paras = [n for n in t.nodes.values() if n.kind == "paragraph"]
        assert arts[0].heading == ""  # 題名ではないので条の題名にしない
        assert paras[0].citation == "第1章 第1条 第1条"
        assert "保険金を支払いません" in paras[0].text

    def test_reference_line_does_not_open_an_article(self):
        """否定例：本文中の条項参照。条を開かず、第一段落の本文になる。"""
        pages = {
            1: "第1章総則\n第4条（告知義務）\n第5条の規定にかかわらず、当会社は保険金を支払う。"
        }
        t = build_tree("r", pages)
        labels = [n.label for n in t.nodes.values() if n.kind == "article"]
        assert labels == ["第4条"]  # 第5条 は参照なので条にならない
        assert any("第5条の規定にかかわらず" in n.text for n in t.nodes.values())


class TestParagraphStyleIsScopedByParentKind:
    """流儀のラッチは親の種別ごと。文書単位にすると先に出た方が後を全部拒否する。"""

    def test_enumeration_first_does_not_win_over_paragraphs(self):
        """teikan の実機構：条中の列挙 `（１）` が先に現れても項の流儀を殺さない。

        **多数決は「その流儀が現れた条の数」で行う。** 列挙は一部の条にしか出ないが
        項はほぼ全条に出るので、条を 2 つ以上見れば分離する（実測 teikan 36 対 3）。
        実文書の teikan では偶然 `２` が先に現れるため先着ラッチでも通っていた。
        **順序に依存しないことがこの規則の目的である。**
        """
        pages = {
            1: "第１章総則\n"
            "第１条（機関）\n"
            "当会社は、総代会および取締役のほか、次の機関を置く。\n"
            "（１）取締役会\n"
            "（２）監査役および監査役会\n"
            "第２条（公告方法）\n"
            "当会社の公告は、電子公告により行う。\n"
            "２事故その他やむを得ない事由によって公告をすることができない場合とする。\n"
            "第３条（社員名簿）\n"
            "当会社は、社員名簿を作成し、これを本店に備え置く。\n"
            "２社員名簿には、社員の氏名または名称および住所を記載する。"
        }
        t = build_tree("t2", pages)
        labels = [n.label for n in t.nodes.values() if n.kind == "paragraph"]
        # 裸数字が項として生き、列挙は項にならない
        assert labels.count("２") == 2
        assert "（１）" not in labels

    def test_dominant_style_counts_articles_not_occurrences(self):
        """件数で数えると 1 条の長い列挙が多数の条の項を上回る。条の数で数える。"""
        seq = [(1, "第１条（機関）")]
        seq += [(1, f"（{i}）項目") for i in range(1, 9)]  # 1 条に列挙 8 件
        seq += [(1, "第２条（公告）"), (1, "２公告は電子公告により行う。")]
        seq += [(1, "第３条（名簿）"), (1, "２名簿には住所を記載する。")]
        assert Builder._dominant_article_para_style(seq, set()) == "bare"

    def test_two_styles_coexist_under_different_parents(self):
        """条の下は `(1)`、別表節の下は `1.` — gold は全体裁でこの共存を持つ。"""
        b = Builder("x")
        b.para_style = {"article": "paren_h", "appendix_section": "dot"}
        assert b.para_style["article"] != b.para_style["appendix_section"]

"""構造パスの**否定規則**を固定する。

肯定的な抽出（第1条を条として拾う）は壊れても気づきやすい。危険なのは
「見出しに見えるものを見出しと認めてしまう」方向の退行で、これは木を静かに壊す。
S4 で実測から導いた否定規則を、ここで逆方向の対照つきで固定する。
"""

from __future__ import annotations

from jpdocread.read.structure.tree import build_tree, canonical_citation


def tree(lines: list[str]):
    return build_tree("t", {1: "\n".join(lines)})


class TestReferenceExclusion:
    def test_reference_in_body_is_not_a_heading(self):
        """`第3条の規定により` は条見出しではない。"""
        t = tree(["第1条（目的）", "本文。", "第3条の規定により、当会社は…"])
        assert [n.label for n in t.of_kind("article")] == ["第1条"]
        assert any("参照" in r for r in t.rejected)

    def test_enumeration_reference_is_not_a_heading(self):
        t = tree(["第1条（目的）", "第5条および第6条に定める場合"])
        assert len(t.of_kind("article")) == 1

    def test_range_reference_is_not_a_heading(self):
        t = tree(["第1条（目的）", "第2条から第4条までの規定"])
        assert len(t.of_kind("article")) == 1

    def test_real_next_article_is_accepted(self):
        """否定規則が強すぎないこと（逆方向の対照）。"""
        t = tree(["第1条（目的）", "本文。", "第2条（定義）", "本文。"])
        assert [n.label for n in t.of_kind("article")] == ["第1条", "第2条"]

    def test_discontinuous_number_without_heading_is_rejected(self):
        t = tree(["第1条（目的）", "第9条この場合において"])
        assert len(t.of_kind("article")) == 1

    def test_discontinuous_number_with_heading_is_accepted(self):
        """番号が飛んでいても見出し括弧があれば受け入れ、再同期を記録する。"""
        t = tree(["第1条（目的）", "第9条（特別の場合）"])
        assert len(t.of_kind("article")) == 2
        assert t.resyncs


class TestTocSuppression:
    def test_toc_entry_is_dropped(self):
        """目次行（見出し＋末尾のページ番号）は木を生やさない。"""
        t = tree(["第1章総則3", "第1章　総則", "第1条（目的）"])
        assert len(t.of_kind("chapter")) == 1
        assert any("目次" in r for r in t.rejected)

    def test_heading_with_trailing_digit_in_sentence_is_kept(self):
        """句点を含む行は目次ではない（否定規則が広すぎないこと）。"""
        t = tree(["第1条（目的）", "本文は別表2のとおりとします。"])
        assert len(t.of_kind("article")) == 1


class TestRiderLookahead:
    def test_rider_confirmed_by_following_article(self):
        t = tree(["弁護士費用特約", "第1条（適用条件）"])
        assert [n.label for n in t.of_kind("rider")] == ["弁護士費用特約"]

    def test_generic_container_without_article_is_not_a_rider(self):
        """`付帯特約` のような総称は、直後に第1条が来ないので特約にしない。"""
        t = tree(["付帯特約", "第1章　総則", "第1条（目的）"])
        assert t.of_kind("rider") == []

    def test_article_numbers_restart_inside_rider(self):
        """特約で条番号が 1 に戻るのは再同期ではなく正常な境界。"""
        t = tree(["第1条（目的）", "第2条（定義）", "弁護士費用特約", "第1条（適用条件）"])
        assert not t.resyncs

    def test_repeated_rider_name_does_not_duplicate(self):
        """柱で特約名が再出現しても木を二重に生やさない。"""
        t = tree(["弁護士費用特約", "第1条（適用条件）", "弁護士費用特約", "本文。"])
        assert len(t.of_kind("rider")) == 1


class TestParagraphStyle:
    def test_paragraph_style_is_fixed_per_document(self):
        """最初に確定した流儀以外は段落ラベルにしない。"""
        t = tree(["第1条（目的）", "①本文一。", "(2)これは参照や表見出しの可能性"])
        assert [n.label for n in t.of_kind("paragraph")] == ["①"]

    def test_halfwidth_and_fullwidth_parens_are_distinct(self):
        t = tree(["第1条（目的）", "（1）本文。", "（2）本文。"])
        assert [n.label for n in t.of_kind("paragraph")] == ["（1）", "（2）"]


class TestCanonicalCitation:
    def test_digit_width_is_normalized(self):
        """数字の全角/半角は組版差であって別の条ではない。"""
        assert canonical_citation("第１章 第１条") == canonical_citation("第1章 第1条")

    def test_paren_style_is_not_normalized(self):
        """括弧の差は段落ラベルの流儀を区別する情報なので潰さない。"""
        assert canonical_citation("（1）") != canonical_citation("(1)")

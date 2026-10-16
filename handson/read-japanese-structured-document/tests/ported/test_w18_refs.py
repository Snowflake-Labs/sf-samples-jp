"""W18（V9）・W19（V10）：参照解決。

規則ごとに肯定例と否定例（本文中の参照を含む）を対で書く。

木は手で組む（実文書の木に依存すると、引用木の変更で参照のテストが壊れる）。
"""

from jpdocread.read.structure.semantics import (
    RE_HEADING_LINE,
    RE_REF_PATH,
    _heading_line_spans,
    resolve_refs,
)
from jpdocread.read.structure.tree import Node, Tree


def _tree() -> Tree:
    """第1章 第1条（項 2）・第2条（項 2、第1項に号 2）、第2章 第1条、別表1（第1・第2）、編 1 の小さな木。"""
    t = Tree(doc_id="t")
    add = t.add
    add(Node("c1", "chapter", label="第1章", citation="第1章"))
    add(Node("c1a1", "article", label="第1条", citation="第1章 第1条", parent_id="c1"))
    add(
        Node(
            "c1a1p1",
            "paragraph",
            label="（1）",
            citation="第1章 第1条 （1）",
            parent_id="c1a1",
            lines=["用語の意味は下表のとおりです。"],
        )
    )
    add(
        Node(
            "c1a1p2",
            "paragraph",
            label="（2）",
            citation="第1章 第1条 （2）",
            parent_id="c1a1",
            lines=["（１）の表に掲げる用語の範囲は、保険証券の記載によります。"],
        )
    )
    add(Node("c1a2", "article", label="第2条", citation="第1章 第2条", parent_id="c1"))
    add(
        Node(
            "c1a2p1",
            "paragraph",
            label="",
            citation="第1章 第2条 第2条",
            parent_id="c1a2",
            lines=["次の各号のいずれかに該当するときは、保険金を支払いません。"],
        )
    )
    add(
        Node(
            "c1a2p1i1",
            "item",
            label="1．",
            citation="第1章 第2条 第2条 1．",
            parent_id="c1a2p1",
            lines=["故意によるもの"],
        )
    )
    add(
        Node(
            "c1a2p1i2",
            "item",
            label="2．",
            citation="第1章 第2条 第2条 2．",
            parent_id="c1a2p1",
            lines=["戦争によるもの"],
        )
    )
    add(
        Node(
            "c1a2p2",
            "paragraph",
            label="②",
            citation="第1章 第2条 ②",
            parent_id="c1a2",
            lines=["第1項第2号に該当するときは、当会社が定めます。"],
        )
    )
    add(Node("c2", "chapter", label="第2章", citation="第2章"))
    add(Node("c2a1", "article", label="第1条", citation="第2章 第1条", parent_id="c2"))
    add(
        Node(
            "c2a1p1",
            "paragraph",
            label="（1）",
            citation="第2章 第1条 （1）",
            parent_id="c2a1",
            lines=[
                "第１章第１条（２）の規定にかかわらず、第１章第２条（保険金を支払わない場合）",
                "第１項の定めによります。別表１第２によります。",
                "第3章保険料の払込み",
            ],
        )
    )
    add(Node("ap1", "appendix", label="別表1", citation="別表1"))
    add(Node("ap1s1", "appendix_section", label="第1", citation="別表1 第1", parent_id="ap1"))
    add(Node("ap1s2", "appendix_section", label="第2", citation="別表1 第2", parent_id="ap1"))
    return t


class TestCompoundReference:
    def test_digit_only_paren_is_a_paragraph_not_a_title(self):
        """M1：`（２）` は題名ではなく項番号。旧規則は題名として食べて条に解決していた。"""
        m = RE_REF_PATH.search("第３章第４条（２）の規定は適用しません。")
        assert m.group("para") == "２"

    def test_title_paren_is_still_consumed(self):
        m = RE_REF_PATH.search("第５条（保険金を支払わない場合）に該当する")
        assert m.group("art") == "５" and m.group("para") is None and m.group("kou") is None

    def test_title_then_kou_and_gou(self):
        m = RE_REF_PATH.search("第4条（告知義務）第1項第2号の告知について")
        assert (m.group("kou"), m.group("gou")) == ("1", "2")

    def test_part_chapter_article(self):
        m = RE_REF_PATH.search("第2編第1章第2条により")
        assert (m.group("part"), m.group("ch"), m.group("art")) == ("2", "1", "2")


class TestHeadingLine:
    def test_chapter_heading_line_is_masked(self):
        assert RE_HEADING_LINE.match("第3章保険料の払込み")
        assert RE_HEADING_LINE.match("第4条備考")
        assert RE_HEADING_LINE.match("別表１後遺障害の区分と支払割合")

    def test_body_line_starting_with_a_reference_is_not_masked(self):
        """本文の折り返しが参照で始まる行（`第１章第１条により…`）は伏せない。"""
        assert not RE_HEADING_LINE.match("第１章第１条により１回の地震等として取り扱われるもの")
        assert not RE_HEADING_LINE.match("第２章第５条の規定は、この特約の保険金について")
        assert not RE_HEADING_LINE.match("別表１に掲げる状態をいいます。")
        assert not RE_HEADING_LINE.match("第１条（用語の定義）に定めるところによります")

    def test_long_or_sentence_line_is_not_a_heading(self):
        assert (
            _heading_line_spans(
                [
                    "第3章保険料の払込みについては当会社が定める方法によるものとし、その詳細は別に定めるところによります"
                ]
            )
            == []
        )
        assert _heading_line_spans(["第3章保険料。"]) == []

    def test_footnote_body_to_end_is_masked(self):
        """M4：最初の脚注行から段落末まで。本文中の脚注参照（…ます（*1）。）は伏せない。"""
        lines = [
            "損害の額を算定します（*１）。",
            "（*１）この費用は第2章第7条によります。",
            "続きの行",
        ]
        spans = _heading_line_spans(lines)
        assert spans == [(len(lines[0]), sum(map(len, lines)))]
        assert _heading_line_spans(["損害の額を算定します（*１）。"]) == []


class TestResolve:
    def setup_method(self):
        self.refs = resolve_refs(_tree())

    def test_compound_paragraph(self):
        assert ("第2章 第1条 （1）", "第1章 第1条 （2）") in self.refs
        # 旧規則の誤り：条に解決しない
        assert ("第2章 第1条 （1）", "第1章 第1条") not in self.refs

    def test_title_then_kou(self):
        assert ("第2章 第1条 （1）", "第1章 第2条 第2条") in self.refs

    def test_kou_gou_in_same_article(self):
        assert ("第1章 第2条 ②", "第1章 第2条 第2条 2．") in self.refs

    def test_appendix_section(self):
        assert ("第2章 第1条 （1）", "別表1 第2") in self.refs

    def test_bare_paragraph_sibling(self):
        assert ("第1章 第1条 （2）", "第1章 第1条 （1）") in self.refs

    def test_heading_line_inside_paragraph_is_not_a_reference(self):
        assert not any(b.startswith("第3章") for _, b in self.refs)


class TestReviewFindings:
    """独立レビュー（V9-6）の指摘を固定する。"""

    def test_appendix_table_number_is_not_a_section(self):
        """指摘 3：`別表2第3表` の `第3` は区分ではない。"""
        from jpdocread.read.structure.semantics import RE_REF_APPENDIX

        assert RE_REF_APPENDIX.search("別表2第3表に掲げる").group(2) is None
        assert RE_REF_APPENDIX.search("別表１第２により算出").group(2) == "２"

    def test_missing_section_does_not_fall_back_to_appendix(self):
        t = _tree()
        t.nodes["c2a1p1"].lines = ["別表１第９によります。"]
        assert not any(
            a == "第2章 第1条 （1）" and b.startswith("別表1") for a, b in resolve_refs(t)
        )

    def test_known_limit_bare_article_body_line_is_masked(self):
        """指摘 5（限界として記録）：助詞なしで続く本文行は見出しと区別できない。挙動を固定して変化を検出する。"""
        assert RE_HEADING_LINE.match("第3条保険金を支払う場合")


class TestW19:
    """W19（V10）：N1 節と探索範囲・N2 括弧の流儀・N4 表の取り込み。肯定例と否定例の対。"""

    def test_section_in_compound_reference(self):
        m = RE_REF_PATH.search("第5章第2節第2条(1)により返還する")
        assert (m.group("ch"), m.group("sec"), m.group("art"), m.group("para")) == (
            "5",
            "2",
            "2",
            "1",
        )

    def test_dot_paragraph_after_title(self):
        m = RE_REF_PATH.search("第３条（保険料の払込みおよび猶予期間）６．の規定により")
        assert m.group("dot") == "６"

    def test_decimal_is_not_a_dot_reference(self):
        from jpdocread.read.structure.semantics import RE_REF_DOT

        assert not RE_REF_DOT.search("日額の１．５倍とします")
        assert RE_REF_DOT.search("５．の貸付によっても")

    def test_enumeration_head_is_not_a_paragraph_reference(self):
        """N2a：行頭の列挙 `（２）監査役…` は参照ではない。`（２）の解除は` は参照。"""
        from jpdocread.read.structure.semantics import RE_REF_PARA

        assert not RE_REF_PARA.search("（２）監査役および監査役会")
        assert RE_REF_PARA.search("（２）の解除は、将来に向かって")
        assert RE_REF_PARA.search("（１）および（２）に定める")

    def test_table_caption_masks_rest_of_paragraph(self):
        lines = [
            "用語の意味は、下表のとおりです。",
            "表1この約款に用いる用語",
            "責任開始期第2章第3条に定める時",
        ]
        assert _heading_line_spans(lines) == [(len(lines[0]), sum(map(len, lines)))]
        # 本文中の「表1に掲げる」は表題行ではない
        assert _heading_line_spans(["表1に掲げる額を支払います。"]) == []

    def test_unique_article_found_outside_scope(self):
        """N1：章の中に無い条は、文書中に一つだけなら文書全体から引く（定款の連番）。"""
        t = _tree()
        t.add(Node("c2a5", "article", label="第5条", citation="第2章 第5条", parent_id="c2"))
        t.nodes["c1a1p1"].lines = ["第５条（機関）により置く取締役会"]
        assert ("第1章 第1条 （1）", "第2章 第5条") in resolve_refs(t)

    def test_ambiguous_article_outside_scope_is_not_guessed(self):
        """N1：一つに決まらないときは当てない（第1条は第1章と第2章の両方にある）。"""
        t = _tree()
        t.add(Node("r", "rider", label="特約", citation="特約"))
        t.add(Node("ra1", "article", label="第2条", citation="特約 第2条", parent_id="r"))
        t.add(
            Node(
                "ra1p1",
                "paragraph",
                label="",
                citation="特約 第2条 第2条",
                parent_id="ra1",
                lines=["第1条（定義）によります。"],
            )
        )
        assert not any(a == "特約 第2条 第2条" for a, _ in resolve_refs(t))


class TestW19Review:
    """W19 の独立レビューの指摘を固定する。"""

    def test_ambiguous_article_without_scope_is_not_guessed(self):
        """指摘 1・4：scope の無い最上位の段落から、2 つある第1条は当てない。"""
        t = _tree()
        t.add(
            Node("top", "paragraph", label="", citation="前文", lines=["第1条（定義）によります。"])
        )
        assert not any(a == "前文" for a, _ in resolve_refs(t))

    def test_kanji_conjunctions_follow_a_reference(self):
        """指摘 2：`又は`・`及び`・`並びに`・`若しくは` が続く `（N）` は参照。"""
        from jpdocread.read.structure.semantics import RE_REF_PARA

        for tail in ("又は", "及び", "並びに", "若しくは"):
            assert RE_REF_PARA.search(f"（２）{tail}（３）の規定")
        assert not RE_REF_PARA.search("（２）監査役")

    def test_dot_after_dai_is_not_a_reference(self):
        """指摘 3：`第1．` は番号付きの見出しで、参照ではない。"""
        from jpdocread.read.structure.semantics import RE_REF_DOT

        assert not RE_REF_DOT.search("第1．の区分")
        assert RE_REF_DOT.search("かつ３．の保険料を")

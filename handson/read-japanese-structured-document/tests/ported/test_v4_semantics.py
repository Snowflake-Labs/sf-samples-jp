"""V4：意味層。肯定例と否定例を対で書く。"""

from jpdocread.read.structure.semantics import RE_FN_BODY, defined_terms


def test_footnote_body_at_line_head():
    assert RE_FN_BODY.match("（*1）等級の認定は、別表1に掲げる区分に従い")
    assert RE_FN_BODY.match("（注2）この場合において")


def test_footnote_reference_in_prose_is_not_body():
    assert not RE_FN_BODY.match("後遺障害をいいます（*1）。")


def test_circled_marker_not_treated_as_footnote():
    # ❶ は表の項目番号でもある（❶証券番号）
    assert not RE_FN_BODY.match("❶証券番号")


def test_defined_term_from_pipe_table_row():
    page = "| ア | 運転者 | 被保険自動車のハンドルを操作している者をいいます。原動機を含みます。 |"
    assert defined_terms({1: page}) == ["運転者"]


def test_row_without_definition_sentence_yields_no_term():
    assert defined_terms({1: "| 第1級 | 3,000万円 |"}) == []

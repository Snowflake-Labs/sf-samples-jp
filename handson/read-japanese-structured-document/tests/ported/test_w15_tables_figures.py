"""W15 — R2 表（パイプ表・列挙表・見出し推定）と図ノード候補の単体テスト。"""

from jpdocread.read.figures_r4 import _chunks, _is_node_text
from jpdocread.read.tables_r2 import (
    enumerated_tables,
    grid_from_pipe,
    infer_header,
    parse_pipe_tables,
)


def test_pipe_tables_skip_separator():
    t = parse_pipe_tables("前文\n| 名称 | 内容 |\n| --- | --- |\n| A | B |\n後文")
    assert t == [[["名称", "内容"], ["A", "B"]]]


def test_header_three_cols_row0_and_col0():
    f = infer_header([["保険金", "支払う場合", "額"], ["対人", "x", "y"]])
    assert f[0] == [True, True, True] and f[1] == [True, False, False]


def test_header_two_col_enumeration_row0_is_data():
    f = infer_header(
        [["①", "対象原付を業務として有償で運送の用に供している間に生じた損害"], ["②", "b"]]
    )
    assert f[0] == [True, False]


def test_header_two_col_definition_row0_is_header():
    f = infer_header([["義務の名称", "内容"], ["損害防止義務", "努めること。"]])
    assert f[0] == [True, True]


def test_enumerated_table_needs_cue():
    txt = "次の表に掲げる場合には適用しません。\n\n① 甲の損害\n② 乙の損害\n\n(4) 以下"
    assert enumerated_tables(txt) == [[["①", "甲の損害"], ["②", "乙の損害"]]]
    assert enumerated_tables("本文です。\n① 甲\n② 乙") == []


def test_grid_expanded_spans_are_one():
    g = grid_from_pipe([["a", "b"], ["c", "d"]], "infer")
    assert all(c["rowspan"] == 1 and c["colspan"] == 1 for c in g) and len(g) == 4


def _w(t, x0, x1, top=10.0):
    return {"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}


def test_chunks_split_on_horizontal_gap():
    ws = [_w("けが人の", 0, 32), _w("救護", 32, 48), _w("警察への連絡", 120, 168)]
    assert [c["text"] for c in _chunks(ws)] == ["けが人の救護", "警察への連絡"]


def test_non_node_text():
    assert not _is_node_text("(1)") and not _is_node_text("第2条(保険金の支払時期)")
    assert not _is_node_text("保険金を支払います。") and _is_node_text("当会社への連絡")

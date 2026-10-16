"""ページ・段をまたぐ表の連結（read/stitch.py）。肯定例と否定例を対で持つ。"""

from __future__ import annotations

from jpdocread.read.stitch import (
    continuation,
    furniture_key,
    is_body_line,
    merge,
    pipe_table_context,
    stitch_tables,
)
from jpdocread.read.tables_r2 import tables_for_doc

HEAD = "| 用語 | 定義 |\n| --- | --- |"


def page(*parts: str) -> str:
    return "\n".join(parts)


def tables_from(layout: dict[int, str], monkeypatch) -> list[dict]:
    """`tables_for_doc` と同じ手順で、ページの Markdown から表のレコードを作る。"""
    from jpdocread.read import tables_r2

    monkeypatch.setattr(tables_r2, "cached_layout_pages", lambda doc_id: layout)
    return tables_for_doc("d")


# ---------------------------------------------------------------- 本文の行と柱


def test_furniture_like_lines_are_not_body():
    for s in ("- 3 -", "16", "H261001", "第2章 賠償責任条項", "", "---"):
        assert not is_body_line(s), s


def test_body_lines():
    for s in (
        "表2 この約款集に用いる用語",
        "# 第1条（定義）",
        "（1）この約款において次の用語を用いる。",
        "下表のとおりとします、",
        "あ" * 31,
    ):
        assert is_body_line(s), s


def test_detected_furniture_adds_long_running_lines():
    """検出した柱（テキスト層）に一致する長い行は柱。形の規則は残る（短い行は検出に無くても柱）。"""
    long_line = "千歳やまぶき終身保険 ご契約のしおり・約款 2026年版 本冊子は架空の約款です"
    furn = {furniture_key(long_line)}
    assert is_body_line(long_line)
    assert not is_body_line(long_line, furn)
    assert not is_body_line("- 3 -", furn)
    assert furniture_key("# 第1章  用語") == furniture_key("第1章 用語")


# ---------------------------------------------------------------- 表の前後の文脈


def test_context_page_end_and_start():
    p3 = page("（1）用語は下表のとおりとします。", "表2 用語", HEAD, "| 甲 | 甲の定義 |", "- 3 -")
    assert pipe_table_context(p3) == [{"body_before": True, "body_after": False}]
    p4 = page("第1章 用語の定義", HEAD, "| 乙 | 乙の定義 |", "表に無い用語は、約款によります。")
    assert pipe_table_context(p4) == [{"body_before": False, "body_after": True}]


def test_running_header_before_first_table_is_furniture():
    """ページの先頭の表の前に 1 行だけある走りヘッダは柱。表題（表N）は本文のまま。"""
    for header in (
        "別表1 高度障害状態",
        "第2編 普通保険約款 第3章 保険契約の変更および消滅",
        "# 第1章 用語の定義",
    ):
        assert (
            pipe_table_context(page(header, HEAD, "| 乙 | 乙の定義 |"))[0]["body_before"] is False
        )
    assert (
        pipe_table_context(page("表3 別の表", HEAD, "| 乙 | 乙の定義 |"))[0]["body_before"] is True
    )
    # 2 行あれば走りヘッダの扱いにしない（間に本文がある）
    two = page("第1章 用語の定義", "（2）次の表に定めます。", HEAD, "| 乙 | 乙の定義 |")
    assert pipe_table_context(two)[0]["body_before"] is True


def test_context_counts_like_parse_pipe_tables():
    """1 行だけのパイプ表は表として数えない（parse_pipe_tables と同じ）。"""
    p = page("| 1 行だけ |", "本文。", HEAD, "| 甲 | 甲の定義 |")
    assert len(pipe_table_context(p)) == 1


# ---------------------------------------------------------------- 続きの証拠


def rec(rows: list[list[str]], pages: list[int], tid: str = "t") -> dict:
    from jpdocread.read.tables_r2 import grid_from_pipe

    return {
        "id": tid,
        "pages": pages,
        "source": "R2_layout_pipe",
        "n_rows": len(rows),
        "n_cols": max(len(r) for r in rows),
        "grid": grid_from_pipe(rows, "infer"),
    }


def test_continuation_repeated_header():
    a = rec([["用語", "定義"], ["甲", "甲の定義"]], [3])
    b = rec([["用語", "定義"], ["乙", "乙の定義"]], [4])
    assert continuation(a, b) == "repeated_header"


def test_continuation_enum_sequence():
    a = rec([["①", "一"], ["②", "二"]], [9])
    b = rec([["③", "三"], ["④", "四"]], [10])
    assert continuation(a, b) == "enum_sequence"
    paren_a = rec([["(1)", "一"], ["(2)", "二"]], [12])
    paren_b = rec([["(3)", "三"], ["(4)", "四"]], [13])
    assert continuation(paren_a, paren_b) == "enum_sequence"


def test_no_continuation():
    a = rec([["用語", "定義"], ["甲", "甲の定義"]], [3])
    assert continuation(a, rec([["名称", "内容"], ["乙", "乙の定義"]], [4])) is None  # 見出しが違う
    assert continuation(a, rec([["用語", "定義", "備考"], ["乙", "乙", "乙"]], [4])) is None  # 列数
    assert (
        continuation(rec([["①", "一"], ["②", "二"]], [9]), rec([["①", "別"], ["②", "表"]], [10]))
        is None
    )
    assert (
        continuation(rec([["①", "一"], ["②", "二"]], [9]), rec([["⑤", "飛"], ["⑥", "び"]], [10]))
        is None
    )


def test_merge_drops_repeated_header_and_keeps_fragments():
    a = rec([["用語", "定義"], ["甲", "甲の定義"]], [3], "a")
    b = rec([["用語", "定義"], ["乙", "乙の定義"], ["丙", "丙の定義"]], [4], "b")
    m = merge(a, b, "repeated_header")
    assert m["pages"] == [3, 4] and m["n_rows"] == 4 and m["id"] == "a"
    texts = [[c["text"] for c in m["grid"] if c["row"] == r] for r in range(m["n_rows"])]
    assert texts == [["用語", "定義"], ["甲", "甲の定義"], ["乙", "乙の定義"], ["丙", "丙の定義"]]
    assert [f["id"] for f in m["fragments"]] == ["a", "b"]
    assert m["stitch"] == {"reasons": ["repeated_header"]}


# ---------------------------------------------------------------- 全体（ページの Markdown から）


def test_stitch_across_page(monkeypatch):
    layout = {
        3: page(
            "（1）用語は下表のとおりとします。", "表2 用語", HEAD, "| 甲 | 甲の定義 |", "- 3 -"
        ),
        4: page("第1章 用語の定義", HEAD, "| 乙 | 乙の定義 |", "表に無い用語は、約款によります。"),
    }
    out = stitch_tables(tables_from(layout, monkeypatch), layout)
    assert len(out) == 1 and out[0]["pages"] == [3, 4] and out[0]["n_rows"] == 3


def test_stitch_across_columns_on_same_page(monkeypatch):
    """同じページで、間に本文の無い 2 つの表（左段の末尾 → 右段の先頭）。"""
    layout = {
        9: page("表6 区分", HEAD, "| 甲 | 甲の定義 |", "", HEAD, "| 乙 | 乙の定義 |", "本文。"),
    }
    out = stitch_tables(tables_from(layout, monkeypatch), layout)
    assert len(out) == 1 and out[0]["n_rows"] == 3


def test_no_stitch_when_body_between(monkeypatch):
    """前の表の後ろに本文がある・次の表の前に表題がある → つながない。"""
    after_body = {
        3: page(HEAD, "| 甲 | 甲の定義 |", "上表の定義は、特約にも適用します。"),
        4: page(HEAD, "| 乙 | 乙の定義 |"),
    }
    assert len(stitch_tables(tables_from(after_body, monkeypatch), after_body)) == 2
    titled = {
        3: page(HEAD, "| 甲 | 甲の定義 |", "- 3 -"),
        4: page("表3 別の表", HEAD, "| 乙 | 乙の定義 |"),
    }
    assert len(stitch_tables(tables_from(titled, monkeypatch), titled)) == 2


def test_no_stitch_two_pages_apart_or_not_last(monkeypatch):
    apart = {3: page(HEAD, "| 甲 | 甲の定義 |"), 5: page(HEAD, "| 乙 | 乙の定義 |")}
    assert len(stitch_tables(tables_from(apart, monkeypatch), apart)) == 2
    # ページ 3 の最後の表は別の表（見出しが違う）。最初の表は次ページとつながない
    not_last = {
        3: page(HEAD, "| 甲 | 甲の定義 |", "", "| 名称 | 内容 |", "| --- | --- |", "| 丙 | 丙 |"),
        4: page(HEAD, "| 乙 | 乙の定義 |"),
    }
    out = stitch_tables(tables_from(not_last, monkeypatch), not_last)
    assert len(out) == 3


def test_enumerated_table_between_does_not_block(monkeypatch):
    """ページの最後のパイプ表の後に列挙表のレコードがあっても、次ページのパイプ表とつなぐ。"""
    layout = {
        9: page(
            "（1）次に掲げる場合。",
            "① 一の場合",
            "② 二の場合",
            "表6 区分",
            HEAD,
            "| 甲 | 甲 |",
            "H1",
        ),
        10: page("第4章 補償", HEAD, "| 乙 | 乙 |", "本文。"),
    }
    tabs = tables_from(layout, monkeypatch)
    assert [t["source"] for t in tabs] == ["R2_layout_pipe", "R2_enumerated", "R2_layout_pipe"]
    out = stitch_tables(tabs, layout)
    assert [t["source"] for t in out] == ["R2_layout_pipe", "R2_enumerated"]
    assert out[0]["pages"] == [9, 10]


def test_stitch_is_deterministic(monkeypatch):
    layout = {
        3: page("表2 用語", HEAD, "| 甲 | 甲の定義 |", "- 3 -"),
        4: page(HEAD, "| 乙 | 乙の定義 |"),
    }
    tabs = tables_from(layout, monkeypatch)
    assert stitch_tables(tabs, layout) == stitch_tables(tabs, layout)

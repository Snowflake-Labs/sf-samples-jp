"""S1: LAYOUT 出力の Markdown 除去（採点の公正性に直結する）。"""

from __future__ import annotations

from jpdocread.read.parse.markdown import has_markdown, paren_width_shift, strip_markdown
from jpdocread.read.parse.r12_cortex import CacheMissError, ParseResult, _requested_pages


class TestStripMarkdown:
    def test_removes_heading_markers(self):
        assert strip_markdown("# 第1条（用語の定義）") == "第1条（用語の定義）"
        assert strip_markdown("### 第2章") == "第2章"

    def test_removes_table_pipes_but_keeps_cell_text(self):
        out = strip_markdown("| 等級 | 支払割合 |")
        assert "等級" in out and "支払割合" in out and "|" not in out

    def test_removes_table_rule_row(self):
        out = strip_markdown("| a | b |\n| --- | --- |\n| 1 | 2 |")
        assert "---" not in out
        assert "1" in out and "2" in out

    def test_preserves_japanese_fullwidth(self):
        """**全角は保持する。** 引用同一性に直結するため。"""
        src = "# 第1条（用語の定義）①〜※【】"
        out = strip_markdown(src)
        for ch in "（）①〜※【】":
            assert ch in out, ch

    def test_does_not_eat_body_text(self):
        src = "この約款において「対物事故」とは、"
        assert strip_markdown(src) == src

    def test_has_markdown_detects_layout_output(self):
        assert has_markdown("# 見出し")
        assert has_markdown("| a | b |")
        assert not has_markdown("普通の日本語の本文です。")


class TestParenWidthShift:
    def test_detects_fullwidth_to_halfwidth_conversion(self):
        """S1 実測：LAYOUT は全角括弧の一部を静かに半角化する。"""
        d = paren_width_shift(pred="(1)を参照", gold="（1）を参照")
        assert d["fullwidth_gold"] == 2
        assert d["fullwidth_pred"] == 0
        assert d["halfwidth_pred"] == 2

    def test_no_shift_reported_when_faithful(self):
        d = paren_width_shift(pred="（1）", gold="（1）")
        assert d["fullwidth_gold"] == d["fullwidth_pred"] == 2
        assert d["halfwidth_pred"] == 0


class TestParseAccounting:
    def test_requested_page_ranges_are_absolute_and_end_exclusive(self):
        assert _requested_pages([(4, 7), (8, 9)]) == (5, 6, 7, 9)

    def test_whole_document_uses_page_count(self):
        # PNG 入力（from_png）は D-019 で削除した。全ページは page_count から 1 始まりで数える
        assert _requested_pages(None, 3) == (1, 2, 3)

    def test_missing_pages_are_not_silent(self):
        result = ParseResult(
            doc_id="d",
            reader="R2",
            options={},
            options_hash="x",
            pages={5: "本文"},
            requested_pages=(5, 6),
        )
        assert result.n_missing_pages == 1
        assert result.n_null_pages == 0

    def test_cache_miss_error_is_explicit(self):
        assert issubclass(CacheMissError, FileNotFoundError)

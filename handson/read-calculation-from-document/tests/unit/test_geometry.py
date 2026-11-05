"""段 R：合成 PDF から行・太字・柱・段・表と図の領域を読む。"""

from __future__ import annotations

from fixtures.synthetic_pdf import Page, Text, build_pdf, contract_pages, text_lines, yakkan_pages

from jpcalc.pdfread.contract_scheme import STANDARD, detect_contract_scheme
from jpcalc.pdfread.furniture import detect_furniture
from jpcalc.pdfread.geometry import extract_geometry


def test_lines_in_reading_order(tmp_path):
    lines, pages = extract_geometry(build_pdf(tmp_path / "y.pdf", yakkan_pages()), "y")
    assert [p.page for p in pages] == [1, 2]
    p2 = [ln for ln in lines if ln.page == 2]
    # 上から順。本文は逐語（全角数字・括弧をそのまま）
    assert p2[0].text == "第１条（保険金を支払う場合）"
    assert all(a.y0 <= b.y0 for a, b in zip(p2, p2[1:], strict=False) if abs(a.x0 - b.x0) < 1)
    assert all(ln.doc_id == "y" for ln in lines)


def test_bold_and_size(tmp_path):
    lines, _ = extract_geometry(build_pdf(tmp_path / "y.pdf", yakkan_pages()), "y")
    head = next(ln for ln in lines if ln.text.startswith("第２条"))
    body = next(ln for ln in lines if ln.text.startswith("当会社は、見本事故"))
    assert "Bold" in (head.font or "") and "Bold" not in (body.font or "")
    assert head.size == 10.5


def test_table_and_figure_regions(tmp_path):
    _, pages = extract_geometry(build_pdf(tmp_path / "y.pdf", yakkan_pages()), "y")
    p2 = pages[1]
    assert len(p2.table_boxes) == 1 and p2.table_cells == [6]
    assert len(p2.figure_boxes) == 1
    assert p2.n_cols == 1


def test_two_columns(tmp_path):
    # 段組は文書全体の性質として決める（段の切れ目の候補が 2 ページ以上要る）ので 2 ページで作る
    def page(n):
        left = text_lines([f"左の段の{n}頁の行その{i}です。" for i in range(20)], x=40)
        right = text_lines([f"右の段の{n}頁の行その{i}です。" for i in range(20)], x=320)
        return Page(texts=left + right)

    lines, pages = extract_geometry(build_pdf(tmp_path / "c2.pdf", [page(1), page(2)]), "c2")
    assert [p.n_cols for p in pages] == [2, 2]
    # 段の切れ目は左の段の行末（約 260pt）から右の段の行頭（320pt）の間
    assert pages[0].gutter is not None and 259 <= pages[0].gutter < 320
    # 左の段をすべて読んでから右の段
    texts = [ln.text for ln in lines if ln.page == 1]
    assert texts.index("左の段の1頁の行その19です。") < texts.index("右の段の1頁の行その0です。")


def test_furniture_running_header_and_page_number(tmp_path):
    pages = [
        Page(
            texts=[Text(250, 820, "見本保険普通保険約款", 8.0), Text(290, 20, str(i), 8.0)]
            + text_lines([f"第{i}条（見本）", "本文の行です。"], top=700)
        )
        for i in range(1, 5)
    ]
    lines, geoms = extract_geometry(build_pdf(tmp_path / "f.pdf", pages), "f")
    furn = detect_furniture(geoms, lines)
    furn_text = {ln.text for ln in lines if (ln.page, ln.line_no) in furn}
    assert furn_text == {"見本保険普通保険約款", "1", "2", "3", "4"}
    # 本文は柱にならない
    assert not any(ln.text.startswith("第") for ln in lines if (ln.page, ln.line_no) in furn)


def test_contract_scheme():
    rows = [ln.s for ln in contract_pages()[0].texts]
    assert detect_contract_scheme(rows) == STANDARD
    assert detect_contract_scheme([t.s for p in yakkan_pages() for t in p.texts]) is None

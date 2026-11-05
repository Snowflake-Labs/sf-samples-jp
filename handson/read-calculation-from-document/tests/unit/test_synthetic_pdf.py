"""合成 PDF の fixture が、読み取りの入力（テキスト層・線・矩形）として pdfplumber で読めること。"""

from __future__ import annotations

import pdfplumber
from fixtures.synthetic_pdf import build_pdf, contract_pages, yakkan_pages


def _read(path):
    with pdfplumber.open(path) as pdf:
        return [(p.extract_text() or "", p.lines, p.rects, p.curves) for p in pdf.pages]


def test_yakkan_fixture(tmp_path):
    pages = _read(build_pdf(tmp_path / "y.pdf", yakkan_pages()))
    assert len(pages) == 2
    text, lines, rects, curves = pages[1]
    for s in (
        "第２条（保険金の額）",
        "免責金額３万円",
        "１００万円",
        "（設例）",
        "保険金の請求",
    ):
        assert s in text
    # 表の罫線（横 4・縦 3）と矢印の線 1 本
    assert len(lines) == 4 + 3 + 1
    # 算式の箱 3 つと、設例の囲み（薄い塗り・線なし）
    assert len(rects) == 4
    box = [r for r in rects if r.get("fill") and not r.get("stroke")]
    color = box[0]["non_stroking_color"]
    gray = color[0] if isinstance(color, (list, tuple)) else color
    assert len(box) == 1 and abs(gray - 0.94) < 1e-6
    # フローチャートの箱 2 つ（閉じたパス）と矢じり 1 つ
    assert len(curves) == 3


def test_contract_fixture(tmp_path):
    pages = _read(build_pdf(tmp_path / "c.pdf", contract_pages()))
    assert len(pages) == 1
    assert "１０営業日以内" in pages[0][0]


def test_char_geometry(tmp_path):
    with pdfplumber.open(build_pdf(tmp_path / "y.pdf", yakkan_pages())) as pdf:
        chars = [c for c in pdf.pages[1].chars if c["text"] == "第"]
    # 1 文字目は x=60、幅は 1 em（10.5pt）
    assert abs(chars[0]["x0"] - 60) < 0.01
    assert abs((chars[0]["x1"] - chars[0]["x0"]) - 10.5) < 0.01


def test_not_written_to_repo(tmp_path):
    p = build_pdf(tmp_path / "sub" / "x.pdf", contract_pages())
    assert p.is_relative_to(tmp_path)

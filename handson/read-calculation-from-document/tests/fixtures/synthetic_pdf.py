"""テスト用の合成 PDF。実データの断片を使わず、架空の条文・表・算式・設例・図から PDF を作る。

フォントを埋め込まずに日本語のテキスト層を持たせるため、Type0 フォント（`Identity-H`）の CID に
Unicode の符号位置をそのまま使い、`ToUnicode` CMap で CID → Unicode を対応させる。pdfplumber（pdfminer）は
ToUnicode からテキストを取り出し、`DW`（1000/1000 em）から文字の bbox を決める。
字形は描かれないが、読み取りの入力はテキスト層と描画要素（線・矩形）なので試験には足りる。
方式は handson/read-japanese-structured-document の tests/fixtures/synthetic_pdf.py と同じで、
位置を指定した文字列と、線・矩形の描画を足した。生成物はテストの一時ディレクトリに作り、コミットしない。

座標は PDF の座標系（左下が原点、単位は pt）。フォントは 2 つ：本文の F1 と、名前に Bold を含む F2
（読み取りは見出しを「フォント名に Bold を含む行」で判定するので、見出しの行は bold=True で書く）。

描き方は、データセットの PDF の描き方に合わせる（読み取りの規則を fixture に合わせて変えないため）：
設例の囲みは線の無い薄い塗りの矩形（灰 0.94）、算式は罫の箱を 1 行に並べ「＝」を含む、
フローチャートの箱は角を落とした閉じたパス（塗り＋線）、矢じりは塗った三角形。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

A4 = (595.0, 842.0)

_TOUNICODE = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
1 beginbfrange
<0000> <FFFF> <0000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end
"""


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # ベースライン
    s: str
    size: float = 10.5
    bold: bool = False


@dataclass(frozen=True)
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    width: float = 0.8


@dataclass(frozen=True)
class Rect:
    """矩形。fill が None なら線だけ、値があればその灰色で塗る（stroke=False なら線を引かない）。"""

    x: float
    y: float
    w: float
    h: float
    width: float = 0.8
    fill: float | None = None
    stroke: bool = True


@dataclass(frozen=True)
class Shape:
    """閉じたパス（点の列）。fill が値ならその灰色で塗り、stroke なら線を引く。"""

    pts: tuple[tuple[float, float], ...]
    fill: float | None = None
    stroke: bool = True
    width: float = 0.8


@dataclass
class Page:
    texts: list[Text] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    rects: list[Rect] = field(default_factory=list)
    paths: list[Shape] = field(default_factory=list)


def _hex(s: str) -> str:
    # BMP の文字だけを使う（架空の条文で足りる）。CID = Unicode の符号位置
    if any(ord(c) > 0xFFFF for c in s):
        raise ValueError("BMP 外の文字は使えない")
    return "".join(f"{ord(c):04X}" for c in s)


def _content(page: Page) -> bytes:
    ops: list[str] = []
    for r in page.rects:
        paint = ("B" if r.stroke else "f") if r.fill is not None else "S"
        fill = f"{r.fill} g " if r.fill is not None else ""
        ops.append(f"{fill}{r.width} w {r.x} {r.y} {r.w} {r.h} re {paint} 0 g")
    for pa in page.paths:
        (x0, y0), *rest = pa.pts
        seg = f"{x0} {y0} m " + " ".join(f"{x} {y} l" for x, y in rest) + " h"
        paint = ("B" if pa.stroke else "f") if pa.fill is not None else "S"
        fill = f"{pa.fill} g " if pa.fill is not None else ""
        ops.append(f"{fill}{pa.width} w {seg} {paint} 0 g")
    for ln in page.lines:
        ops.append(f"{ln.width} w {ln.x0} {ln.y0} m {ln.x1} {ln.y1} l S")
    for t in page.texts:
        font = "F2" if t.bold else "F1"
        ops.append(f"BT /{font} {t.size} Tf {t.x} {t.y} Td <{_hex(t.s)}> Tj ET")
    return "\n".join(ops).encode("ascii")


def build_pdf(path: Path, pages: Sequence[Page]) -> Path:
    """pages から PDF を書いて path を返す。"""
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    tounicode = add(b"<< /Length %d >>\nstream\n" % len(_TOUNICODE) + _TOUNICODE + b"\nendstream")

    def add_font(name: str) -> int:
        desc = add(
            f"<< /Type /FontDescriptor /FontName /{name} /Flags 4 /FontBBox [0 -120 1000 880] "
            "/ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>".encode()
        )
        cid = add(
            f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{name} "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            f"/FontDescriptor {desc} 0 R /DW 1000 /CIDToGIDMap /Identity >>".encode()
        )
        return add(
            f"<< /Type /Font /Subtype /Type0 /BaseFont /{name} /Encoding /Identity-H "
            f"/DescendantFonts [{cid} 0 R] /ToUnicode {tounicode} 0 R >>".encode()
        )

    font = add_font("JpcalcSynth")
    font_bold = add_font("JpcalcSynth-Bold")
    pages_id = len(objs) + 1 + 2 * len(pages)  # ページとその内容を先に足し、最後に /Pages
    page_ids = []
    for page in pages:
        body = _content(page)
        content = add(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                f"/Resources << /Font << /F1 {font} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content} 0 R >>".encode()
            )
        )
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    assert add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()) == pages_id
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, b in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + b + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


# 見出しの行（太字で書く）：章・条・別表
def _is_head(s: str) -> bool:
    return (s.startswith("第") and ("条（" in s or "章" in s[:5])) or s.startswith(("別表", "付表"))


def text_lines(
    lines: Sequence[str],
    *,
    x: float = 60.0,
    top: float = 780.0,
    leading: float = 18.0,
    size: float = 10.5,
) -> list[Text]:
    """行を上から並べる。章・条・別表の見出しの行は太字にする。"""
    return [Text(x, top - i * leading, s, size, bold=_is_head(s)) for i, s in enumerate(lines)]


def table(
    x: float,
    top: float,
    col_widths: Sequence[float],
    rows: Sequence[Sequence[str]],
    *,
    row_h: float = 20.0,
    size: float = 9.5,
) -> tuple[list[Text], list[Line]]:
    """罫線で囲んだ表（全セルに罫線）。文字はセルの左下寄せ。"""
    total_w = sum(col_widths)
    lines = [Line(x, top - i * row_h, x + total_w, top - i * row_h) for i in range(len(rows) + 1)]
    xs = [x]
    for w in col_widths:
        xs.append(xs[-1] + w)
    bottom = top - len(rows) * row_h
    lines += [Line(cx, top, cx, bottom) for cx in xs]
    texts = [
        Text(xs[c] + 4, top - (r + 1) * row_h + 6, cell, size)
        for r, row in enumerate(rows)
        for c, cell in enumerate(row)
    ]
    return texts, lines


# ---- 架空の文書（実在の約款・契約書の文言ではない） --------------------------------------------------


def _node(x: float, y: float, w: float, h: float, c: float = 3.0) -> Shape:
    """角を落とした箱（点 8 つの閉じたパス。塗り＋線）。"""
    pts = (
        (x + c, y),
        (x + w - c, y),
        (x + w, y + c),
        (x + w, y + h - c),
        (x + w - c, y + h),
        (x + c, y + h),
        (x, y + h - c),
        (x, y + c),
    )
    return Shape(pts, fill=1.0, stroke=True)


def _arrow(x0: float, y: float, x1: float) -> tuple[Line, Shape]:
    """右向きの矢印：線と、塗った三角形の矢じり（6pt）。"""
    return Line(x0, y, x1 - 6, y), Shape(((x1 - 6, y + 3), (x1, y), (x1 - 6, y - 3)), fill=0.0)


def yakkan_pages() -> list[Page]:
    """保険約款に似た架空の 2 ページ：表紙／条・項・号・算式・表・設例の囲み・2 箱のフローチャート。"""
    cover = Page(
        texts=text_lines(["見本保険", "普通保険約款", "架空見本損害保険株式会社"], top=600)
    )
    body = text_lines(
        [
            "第１条（保険金を支払う場合）",
            "当会社は、見本事故によって生じた損害に対して、この約款に従い保険金を支払います。",
            "第２条（保険金の額）",
            "保険金の額は、次の算式によって算出した額とします。",
        ]
    )
    # 算式：罫の箱を 1 行に並べる（項・演算子・項・＝・結果）
    fy = 690.0
    formula_boxes = [Rect(70, fy, 70, 20), Rect(160, fy, 90, 20), Rect(270, fy, 70, 20)]
    formula_texts = [
        Text(74, fy + 6, "損害の額", 9.5),
        Text(145, fy + 6, "－", 9.5),
        Text(164, fy + 6, "免責金額３万円", 9.5),
        Text(255, fy + 6, "＝", 9.5),
        Text(274, fy + 6, "保険金の額", 9.5),
    ]
    body2 = text_lines(
        [
            "２．前項の額は、別表１の支払限度額を限度とします。",
            "第３条（保険金を支払わない場合）",
            "当会社は、次のいずれかに該当する損害に対しては、保険金を支払いません。",
            "（１）故意によって生じた損害",
            "（２）保険期間の外で生じた損害",
        ],
        top=660,
    )
    t_texts, t_lines = table(
        60,
        560,
        [120, 120],
        [["区分", "支払限度額"], ["Ａ型", "１００万円"], ["Ｂ型", "２００万円"]],
    )
    # 設例の囲み：線の無い薄い塗り
    example_box = Rect(60, 452, 470, 30, fill=0.94, stroke=False)
    example = [
        Text(70, 463, "（設例）損害の額が１０万円のとき、保険金の額は７万円となります。", 9.5)
    ]
    # フローチャート：角を落とした箱 2 つと矢印。図は下のキャプション（「図N」）で見つかる
    flow_texts = [
        Text(80, 392, "事故の発生", 9.5),
        Text(290, 392, "保険金の請求", 9.5),
        Text(60, 360, "図１　保険金の請求の流れ", 9.0),
    ]
    a_line, a_head = _arrow(180, 395, 280)
    return [
        cover,
        Page(
            texts=body + formula_texts + body2 + t_texts + example + flow_texts,
            lines=t_lines + [a_line],
            rects=formula_boxes + [example_box],
            paths=[_node(70, 380, 110, 30), _node(280, 380, 120, 30), a_head],
        ),
    ]


def contract_pages() -> list[Page]:
    """ビジネス契約書に似た架空の 1 ページ：当事者の宣言・条・項（番号は「２」の形）・営業日の期限。"""
    return [
        Page(
            texts=text_lines(
                [
                    "見本業務委託契約書",
                    "株式会社アカシ（以下「甲」という。）と株式会社イズミ（以下「乙」という。）は、次のとおり契約を締結する。",
                    "第１条（委託料）",
                    "甲は、乙に対し、委託料として月額５０万円（税別）を支払う。",
                    "２甲は、毎月末日締めで、翌月末日までに前項の委託料を支払う。",
                    "第２条（遅延損害金）",
                    "甲が支払を遅延したときは、遅延日数に応じ年１４．６％の割合による遅延損害金を支払う。",
                    "第３条（検収）",
                    "甲は、成果物の受領後１０営業日以内に検収を行う。",
                ]
            )
        )
    ]


def contract_kanji_pages() -> list[Page]:
    """漢数字の条番号の架空の契約書：太字の題名の行の次に「第一条…」（題名と条が別の行）。

    3 行目の本文は行頭が「第三条」の参照（題名の直後ではない）で、条にしてはいけない。
    """
    rows = [
        ("見本工事請負契約約款", False),
        (
            "株式会社アカシ（以下「甲」という。）と株式会社イズミ（以下「乙」という。）は、次のとおり契約する。",
            False,
        ),
        ("（総則）", True),
        ("第一条甲および乙は、この約款に従い、契約を履行する。", False),
        ("（請負代金）", True),
        ("第二条甲は、乙に対し、請負代金として５００万円を支払う。", False),
        ("第三条に定める検査の後、甲は前条の代金を支払う。", False),
        ("（検査）", True),
        ("第三条甲は、工事の完成の通知を受けた日から１４日以内に検査を行う。", False),
        ("（再委託）", True),
        ("第三条の二乙は、甲の承諾なく第三者に再委託してはならない。", False),
        ("（解除）", True),
        (
            "第四条甲は、乙が期限までに工事を完成しないときは、この契約を解除することができる。",
            False,
        ),
    ]
    return [
        Page(texts=[Text(60.0, 780.0 - i * 18.0, s, 10.5, bold=b) for i, (s, b) in enumerate(rows)])
    ]

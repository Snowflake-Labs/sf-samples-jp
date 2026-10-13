"""テスト用の合成 PDF。実データの断片を使わず、架空の条文から PDF を作る。

フォントを埋め込まずに日本語のテキスト層を持たせるため、Type0 フォント（`Identity-H`）の CID に
Unicode の符号位置をそのまま使い、`ToUnicode` CMap で CID → Unicode を対応させる。pdfplumber（pdfminer）は
ToUnicode からテキストを取り出し、`W` の既定幅（1000/1000 em）から文字の bbox を決める。
字形は描かれない（表示は代替フォント）が、読み取りの入力はテキスト層なので試験には足りる。
生成物はテスト実行時の一時ディレクトリに作り、コミットしない。
"""

from __future__ import annotations

from collections.abc import Sequence
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


def _hex(s: str) -> str:
    # BMP の文字だけを使う（架空の条文で足りる）。CID = Unicode の符号位置
    if any(ord(c) > 0xFFFF for c in s):
        raise ValueError("BMP 外の文字は使えない")
    return "".join(f"{ord(c):04X}" for c in s)


def _content(
    lines: Sequence[str], *, size: float, left: float, top: float, leading: float
) -> bytes:
    ops = ["BT", f"/F1 {size} Tf", f"{leading} TL", f"{left} {top} Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append("T*")
        ops.append(f"<{_hex(line)}> Tj")
    ops.append("ET")
    return "\n".join(ops).encode("ascii")


def build_pdf(
    path: Path,
    pages: Sequence[Sequence[str]],
    *,
    size: float = 10.5,
    left: float = 60.0,
    top: float = 780.0,
    leading: float = 18.0,
) -> Path:
    """pages（ページごとの行の列）から PDF を書く。"""
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    font_desc = add(
        b"<< /Type /FontDescriptor /FontName /JpdocSynth /Flags 4 /FontBBox [0 -120 1000 880] "
        b"/ItalicAngle 0 /Ascent 880 /Descent -120 /CapHeight 700 /StemV 80 >>"
    )
    cid_font = add(
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /JpdocSynth "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        + f"/FontDescriptor {font_desc} 0 R /DW 1000 /CIDToGIDMap /Identity >>".encode()
    )
    tounicode = add(b"<< /Length %d >>\nstream\n" % len(_TOUNICODE) + _TOUNICODE + b"\nendstream")
    font = add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /JpdocSynth /Encoding /Identity-H "
        + f"/DescendantFonts [{cid_font} 0 R] /ToUnicode {tounicode} 0 R >>".encode()
    )
    pages_id = len(objs) + 1 + 2 * len(pages)  # ページとその内容を先に足し、最後に /Pages
    page_ids = []
    for lines in pages:
        body = _content(lines, size=size, left=left, top=top, leading=leading)
        content = add(b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream")
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>".encode()
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


# 架空の条文（実在の約款・契約書の文言ではない）。実文書と同じく 1 ページ目を短い表紙にする
# （移植元の規則は 1 ページ目の文字数が少なければ表紙として構造の入力から外す。structure/pages.cover_pages）
YAKKAN_PAGES = [
    ["見本保険", "普通保険約款", "架空見本損害保険株式会社"],
    [
        "第１章　総則",
        "第１条（この約款の目的）",
        "この約款は、架空の見本保険について定めます。",
        "第２条（用語の定義）",
        "この約款において、次の用語の意味は、次のとおりとします。",
        "（１）　見本事故",
        "見本の目的で定める事故をいいます。",
        "（２）　見本期間",
        "保険証券に記載された期間をいいます。",
        "第２章　補償内容",
        "第３条（保険金を支払う場合）",
        "当会社は、第２条に定める見本事故によって生じた損害に対して、保険金を支払います。",
        "２　前項の保険金の額は、保険証券に記載された金額とします。",
        "第４条（保険金を支払わない場合）",
        "当会社は、次のいずれかに該当する損害に対しては、保険金を支払いません。",
        "（１）　故意によって生じた損害",
        "（２）　見本期間の外で生じた損害",
    ],
]

CONTRACT_PAGES = [
    ["見本業務委託契約書"],
    [
        "株式会社アカシ（以下「甲」という。）と株式会社イズミ（以下「乙」という。）は、",
        "次のとおり業務委託契約（以下「本契約」という。）を締結する。",
        "第１条（目的）",
        "甲は、乙に対し、見本業務（以下「委託業務」という。）を委託し、乙はこれを受託する。",
        "第２条（委託料）",
        "１　甲は、乙に対し、委託業務の対価として委託料を支払う。",
        "２　前項の委託料は、別途定める。",
        "第３条（秘密保持）",
        "乙は、委託業務に関して知り得た情報を第三者に開示してはならない。",
        "第４条（有効期間）",
        "本契約の有効期間は、締結日から１年間とする。",
    ],
]

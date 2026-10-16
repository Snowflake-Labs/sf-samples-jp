"""表の格子を R2（`AI_PARSE_DOCUMENT` LAYOUT）のパイプ表から作る（課金 0・W15 R1/R2）。

W14 までの `out/*.json` は表の領域だけを持ち、`grid` は None だった。
P3（領域クロップ ＋ `AI_COMPLETE`）は PILOT の表にしか回していないためである。
T16（`eval/t16_layout_tables.py`）で、LAYOUT のパイプ表だけでもセル F1 0.80
（P3 は 0.84）が出ると分かったので、**全文書・全ページの表をこの経路で出す**。

**LAYOUT が返せないもの：** `rowspan`/`colspan`（結合は同値の繰り返しか空セルになる）と、
多段の見出し（Markdown 表の見出しは 1 行だけ）。本モジュールの格子は「展開後の格子」である。

見出しの推定（`is_header`）はパイプ表の形から決める。gold は参照しない（`guard`）。
"""

from __future__ import annotations

import json
import re

from ..common.paths import WORK

RE_SEP = re.compile(r"^\|[\s:\-|]+\|$")


def parse_pipe_tables(text: str) -> list[list[list[str]]]:
    """ページの Markdown からパイプ表を順に取り出す。各表は行 × 列の文字列。"""
    tables: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            if RE_SEP.match(s):
                continue
            cur.append([c.strip() for c in s.strip("|").split("|")])
            continue
        if cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return [t for t in tables if len(t) >= 2]


def grid_from_pipe(rows: list[list[str]], header: str = "row0") -> list[dict]:
    """パイプ表を格子セルの列にする。

    `header="row0"`：1 行目だけを見出しとする（T16 と同じ）。
    `header="infer"`：`infer_header` で推定する（R2）。
    """
    width = max(len(r) for r in rows)
    flags = infer_header(rows) if header == "infer" else None
    out: list[dict] = []
    for ri, r in enumerate(rows):
        for ci in range(width):
            txt = r[ci] if ci < len(r) else ""
            h = flags[ri][ci] if flags else ri == 0
            out.append(
                {"row": ri, "col": ci, "rowspan": 1, "colspan": 1, "text": txt, "is_header": h}
            )
    return out


RE_ENUM_HEAD = re.compile(r"^(?:[①-⑳❶-❿]|[（(]?[0-9０-９]{1,2}[）).．]|[ア-ン][.．）)]?$)")


def _row0_is_header(rows: list[list[str]]) -> bool:
    """1 行目が列見出しか。

    3 列以上の表は 1 行目が見出しである。2 列の表は、「①…｜本文」の列挙表
    （1 行目もデータ）と「名称｜内容」の定義表（1 行目が見出し）の 2 種類がある。
    1 行目の左セルが列挙記号でなく、右セルが短く句点を含まないものを見出しとする。
    **この規則は W15 で ALL の表の形（見出し型 3 種）を見て決めた。標本内である**。
    """
    width = max(len(r) for r in rows)
    if width >= 3:
        return True
    r0 = rows[0] + [""] * (2 - len(rows[0]))
    left, right = r0[0].strip(), r0[1].strip()
    if not left or RE_ENUM_HEAD.match(left):
        return False
    return len(right) <= 12 and "。" not in right


def infer_header(rows: list[list[str]]) -> list[list[bool]]:
    """見出しセルを表の形から推定する：列 0 は行見出し、行 0 は `_row0_is_header` による。

    多段の見出し行（gold で 34 表）は Markdown 表では表現できないので推定しない。
    """
    width = max(len(r) for r in rows)
    h0 = _row0_is_header(rows)
    return [[ci == 0 or (ri == 0 and h0) for ci in range(width)] for ri in range(len(rows))]


def cached_layout_pages(doc_id: str) -> dict[int, str]:
    """`work/parse/` の R2 キャッシュから最もページ数の多いペイロードを採る（課金 0）。"""
    best: dict[int, str] = {}
    for f in (WORK / "parse").glob(f"{doc_id}__R2__*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        pages = {int(k): v for k, v in (d.get("pages") or {}).items()}
        if len(pages) > len(best):
            best = pages
    return best


# 試行 2 で「次に掲げる」「次のいずれか」と `（N）` を加えた（gold 表の再現 390→418/422、
# 表の精度 0.976→0.942。偽の表は gold が本文の列挙として扱う箇所。W15 R1 の記録を参照）。
RE_TABLE_CUE = re.compile(r"(?:下表|次の表|上表|別表|表に掲げる|次表|次に掲げる|次のいずれか)")
RE_ENUM_ROW = re.compile(r"^([①-⑳❶-❿]|[（(][0-9０-９]{1,2}[）)])\s*(.+)$")


def _series(mark: str) -> str:
    return "circled" if re.match(r"[①-⑳❶-❿]", mark) else "paren"


def enumerated_tables(text: str) -> list[list[list[str]]]:
    """罫線の無い列挙表（`① 本文` の行の並び）を 2 列の表として取り出す（W15 R1）。

    LAYOUT はこの種の表をパイプ表にせず、平文の行として返す。本文中の列挙と区別するため、
    **直前の段落が表を名指ししている（`下表`・`次の表`…）ときだけ**表とみなす。
    手がかりは文書の記述だけであり、gold は参照しない。
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text)]
    out: list[list[list[str]]] = []
    cue = False
    cur: list[list[str]] = []
    for p in paras:
        if not p:
            continue
        m = RE_ENUM_ROW.match(p)
        # 表の行は最初の行と同じ記号系に限る（丸数字の表の後の `(4)` は次の項であって表の行ではない）
        if m and cur and _series(m.group(1)) != _series(cur[0][0]):
            m = None
        if m and (cue or cur):
            cur.append([m.group(1), m.group(2).strip()])
            continue
        if len(cur) >= 2:
            out.append(cur)
        cur = []
        cue = bool(RE_TABLE_CUE.search(p)) and not p.startswith("|")
    if len(cur) >= 2:
        out.append(cur)
    return out


def tables_for_doc(doc_id: str, header: str = "infer", enum: bool = True) -> list[dict]:
    """全ページの表（パイプ表 ＋ 列挙表）を `out` の表レコードにする。"""
    out = []
    for page, text in sorted(cached_layout_pages(doc_id).items()):
        found = [("R2_layout_pipe", t) for t in parse_pipe_tables(text)]
        if enum:
            found += [("R2_enumerated", t) for t in enumerated_tables(text)]
        for k, (src, rows) in enumerate(found):
            out.append(
                {
                    "id": f"r2t_p{page:03d}_{k}",
                    "pages": [page],
                    "source": src,
                    "n_rows": len(rows),
                    "n_cols": max(len(r) for r in rows),
                    "grid": grid_from_pipe(rows, header),
                }
            )
    return out

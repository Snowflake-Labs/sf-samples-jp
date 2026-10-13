"""図のノードのラベルを R4 の幾何から取る（課金 0・W15 R3）。

W14 までの `out` の図は領域（bbox）だけで、`graph` は None だった（P4 は PILOT のみ）。
ここでは検出した図領域の中にある R4 の行を**ノード候補のラベル**として出す。
辺（矢印）は出さない。辺は線分と矢頭の幾何を要し、この経路では推定しない。

gold は参照しない（`guard`）。
"""

from __future__ import annotations

import re

from .geometry import read_pages

# ノードでない塊：キャプション・注記（図番号・※）、本文の条見出し（領域のはみ出し）、
# 番号札だけの塊（`(1)`・`3`）。W15 R3 試行 2 で後 2 者を加えた。
RE_NOT_NODE = re.compile(r"^(?:図[0-9０-９]|※|（注|\(注|第[0-9０-９]+条|[()（）0-9０-９.．]+$)")


RE_PROSE = re.compile(r"[。]$")
# これより長い塊は本文（図領域が本文へはみ出した部分）とみなす。試行 2 で 25→16。
# 16 と 20 の 2 値を ALL で比べて選んだ（標本内の選択。16 字超は gold ラベルの約 5%）。
MAX_NODE_CHARS = 16


def _chunks(words: list[dict], gap_ratio: float = 1.5) -> list[dict]:
    """図領域内の語を、同じ行の中でも**横の空きで**区切ってノード候補の塊にする。

    R4 の行組立は段組み内で横に並ぶ語を 1 行に結合するので、横に並ぶ図のノード
    （`けが人の救護` と `警察への連絡`）が 1 つのラベルになっていた（W15 R3 の分析）。
    """
    from .geometry import _cluster_words_to_lines, _join_words

    out = []
    for row in _cluster_words_to_lines(words):
        row = sorted(row, key=lambda w: w["x0"])
        cur = [row[0]]
        for w in row[1:]:
            prev = cur[-1]
            cw = (prev["x1"] - prev["x0"]) / max(1, len(prev["text"]))
            if w["x0"] - prev["x1"] > gap_ratio * cw:
                out.append(cur)
                cur = [w]
            else:
                cur.append(w)
        out.append(cur)
    return [
        {
            "text": _join_words(c),
            "bbox": [
                min(w["x0"] for w in c),
                min(w["top"] for w in c),
                max(w["x1"] for w in c),
                max(w["bottom"] for w in c),
            ],
        }
        for c in out
    ]


def _is_node_text(t: str) -> bool:
    return (
        bool(t) and not RE_NOT_NODE.match(t) and not RE_PROSE.search(t) and len(t) <= MAX_NODE_CHARS
    )


def figures_for_doc(doc_id: str) -> list[dict]:
    """全ページの図領域について、領域内の語の塊をノード候補にする。PDF を直接読む（課金 0）。

    行単位（`read_lines`）の版は node F1 0.2279 だった。語単位で横の空きを区切ると 0.6142、
    非ノードの除外を加えて 0.7225（W15 R3）。
    """
    import pdfplumber

    from ..common.paths import doc_pdf

    out = []
    pages = {p.page: p for p in read_pages(doc_id)}
    with pdfplumber.open(doc_pdf(doc_id)) as pdf:
        for pno, pg in sorted(pages.items()):
            if not pg.figure_boxes:
                continue
            words = pdf.pages[pno - 1].extract_words(keep_blank_chars=False)
            for k, box in enumerate(pg.figure_boxes):
                inside = [
                    w
                    for w in words
                    if box[0] - 2 <= (w["x0"] + w["x1"]) / 2 <= box[2] + 2
                    and box[1] - 2 <= (w["top"] + w["bottom"]) / 2 <= box[3] + 2
                ]
                nodes = (
                    [
                        {"id": f"n{i}", "label": c["text"].strip(), "bbox": c["bbox"]}
                        for i, c in enumerate(
                            x for x in _chunks(inside) if _is_node_text(x["text"].strip())
                        )
                    ]
                    if inside
                    else []
                )
                out.append(
                    {
                        "id": f"r4f_p{pno:03d}_{k}",
                        "pages": [pno],
                        "bbox": box,
                        "source": "R4_words_in_region",
                        "nodes": nodes,
                        "edges": None,
                    }
                )
    return out

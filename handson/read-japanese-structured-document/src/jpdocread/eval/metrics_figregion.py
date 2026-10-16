"""図の領域の採点（採点側専用。既存の `figure_scores` の値は変えない）。

図の領域（出力の `figure_regions`）は、領域ごとに S40 で `AI_COMPLETE` を 1 回呼ぶ単位である。
図の採点（`figure_scores`）は正解の図ごとに「同じページで最もよく重なる予測の図」を選ぶので、
**正解の図と対応しない領域は減点されないが、呼び出しの課金だけを生む。** これを数える。

- **対応した領域**（`n_matched`）：ある正解の図にとって、同じページで最もよく重なる領域（`figure_scores` と同じ選び方）
- **余分な領域**（`n_extra`）：どの正解の図にも選ばれない領域。重なる正解の要素の種類（脚注・表・署名欄…）で内訳を取る
- **取りこぼし**（`n_gold_missed`）：同じページに重なる領域が 1 つも無い正解の図

内訳の重なりは「交差 ÷ 小さい方の面積 ≥ `OVERLAP_MIN`」。領域は余白（パディング）を足して切り出すので、
領域の面積で割ると小さな要素ほど重なりが小さく出る。小さい方で割ると、要素が領域に収まるかを測れる。
"""

from __future__ import annotations

from collections import Counter

from ..common.bbox import overlap_area, overlap_of_smaller

OVERLAP_MIN = 0.6
# 内訳に使う正解の要素の種類。これ以外の要素だけに重なる領域は `other`、どれにも重ならなければ `none`
KINDS = (
    "figure",
    "table",
    "footnote",
    "box",
    "formula_box",
    "sig_block",
    "stamp_duty",
    "table_note",
    "caption",
)


def _boxes(e: dict) -> list[tuple[int, list[float]]]:
    """要素の (ページ, bbox) の組。`pages` と `bboxes` の数が同じなら順に対応させ、違えば先頭のページに置く。"""
    pages = e.get("pages") or []
    boxes = e.get("bboxes") or []
    if not pages:
        return []
    if len(pages) == len(boxes):
        return list(zip(pages, boxes, strict=True))
    return [(pages[0], b) for b in boxes]


Region = tuple[int, list[float]]  # (ページ, bbox)


def _regions(pred: dict) -> list[Region]:
    return [
        (r["pages"][0], r["bbox"])
        for r in pred.get("figure_regions") or []
        if r.get("pages") and r.get("bbox")
    ]


def match_gold_figures(elements: list[dict], regions: list[Region]) -> tuple[set[int], int, int]:
    """正解の図ごとに、同じページで最もよく重なる領域を選ぶ（`figure_scores` と同じ選び方）。

    戻り値は (選ばれた領域の添字, 正解の図の数, 取りこぼした正解の図の数)。重なりが 0 なら取りこぼし。
    """
    matched: set[int] = set()
    n_gold = missed = 0
    for e in elements:
        if e.get("kind") != "figure":
            continue
        page = (e.get("pages") or [None])[0]
        gbox = (e.get("bboxes") or [None])[0]
        if gbox is None:
            continue
        n_gold += 1
        cands = [(i, overlap_area(b, gbox)) for i, (p, b) in enumerate(regions) if p == page]
        hit = max(cands, key=lambda x: x[1], default=None)
        if hit is None or hit[1] <= 0:
            missed += 1
        else:
            matched.add(hit[0])
    return matched, n_gold, missed


def extra_kind(region: Region, gold_boxes: list[tuple[str, int, list[float]]]) -> str:
    """余分な領域が重なる正解の要素の種類。`KINDS` のうち最もよく重なるもの、`KINDS` 外だけなら other、無ければ none。"""
    page, rb = region
    score_by_kind: dict[str, float] = {}
    for kind, p, b in gold_boxes:
        if p != page:
            continue
        s = overlap_of_smaller(rb, b)
        if s >= OVERLAP_MIN:
            score_by_kind[kind] = max(score_by_kind.get(kind, 0.0), s)
    if not score_by_kind:
        return "none"
    known = {k: v for k, v in score_by_kind.items() if k in KINDS}
    return max(known, key=known.get) if known else "other"


def figure_region_scores(elements: list[dict], pred: dict) -> dict:
    regions = _regions(pred)
    matched, n_gold, missed = match_gold_figures(elements, regions)
    gold_boxes = [(e["kind"], p, b) for e in elements if e.get("kind") for p, b in _boxes(e)]
    extra = Counter(extra_kind(r, gold_boxes) for i, r in enumerate(regions) if i not in matched)
    return {
        "n_regions": len(regions),
        "n_gold_figures": n_gold,
        "n_matched": len(matched),
        "n_extra": len(regions) - len(matched),
        "n_gold_missed": missed,
        "extra_by_kind": dict(sorted(extra.items())),
    }


def summarize_figure_regions(rows: list[dict]) -> dict:
    n_regions = sum(r["n_regions"] for r in rows)
    n_matched = sum(r["n_matched"] for r in rows)
    n_gold = sum(r["n_gold_figures"] for r in rows)
    n_missed = sum(r["n_gold_missed"] for r in rows)
    extra: Counter = Counter()
    for r in rows:
        extra.update(r["extra_by_kind"])
    return {
        "n_regions": n_regions,
        "n_gold_figures": n_gold,
        "n_matched": n_matched,
        "n_extra": n_regions - n_matched,
        "n_gold_missed": n_missed,
        "region_precision": round(n_matched / n_regions, 4) if n_regions else 0.0,
        "gold_recall": round((n_gold - n_missed) / n_gold, 4) if n_gold else 0.0,
        "extra_by_kind": dict(sorted(extra.items())),
    }

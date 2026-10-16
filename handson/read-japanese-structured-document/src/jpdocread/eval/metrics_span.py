"""ページ・段をまたぐ表の採点（採点側専用。既存の `table_scores` の値は変えない）。

正解の表を「またぎ方」で 3 つに分ける。

- `single`：1 ページ・1 段に収まる表
- `page`：2 ページ以上にまたがる表（`pages` が 2 つ以上）
- `column`：1 ページの中で段をまたぐ表（`pages` は 1 つで `bboxes` が 2 つ以上）

1 つの表を 1 つとして読めたかを、セル F1 とは別に次の量で測る。

- **分断度**（`n_fragments`）：その正解の表に固有のセル本文を 2 つ以上含む予測の表の数。理想は 1。
  0 は対応する予測の表が無いこと。
- **誤連結**（`n_overmerged`）：1 つの予測の表が、2 つ以上の正解の表の固有のセル本文をそれぞれ 2 つ以上含むこと。
  別々の表を 1 つにつないだ誤りで、つながないことよりも悪い（2 つの表の採点をまとめて壊す）。

「固有のセル本文」は、正規化した本文のうち同じ文書の他の正解の表に現れないもの。見出しの「用語」「定義」のように
表をまたいで繰り返す本文で、断片の帰属を取り違えないようにする。
"""

from __future__ import annotations

from collections import Counter

from .metrics_table import norm_cell

SPANS = ("single", "page", "column")


def span_kind(table: dict) -> str:
    """正解の表要素（`kind == "table"`）のまたぎ方。"""
    if len(table.get("pages") or []) > 1:
        return "page"
    if len(table.get("bboxes") or []) > 1:
        return "column"
    return "single"


def _texts(grid: list[dict] | None) -> set[str]:
    return {t for t in (norm_cell(c.get("text")) for c in grid or []) if t}


def unique_texts(gold_grids: dict[str, list[dict]]) -> dict[str, set[str]]:
    """正解の表ごとに、同じ文書の他の正解の表に現れないセル本文の集合。"""
    texts = {tid: _texts(g) for tid, g in gold_grids.items()}
    count: Counter = Counter(t for s in texts.values() for t in s)
    return {tid: {t for t in s if count[t] == 1} for tid, s in texts.items()}


def span_scores(
    gold_tables: list[dict],
    gold_grids: dict[str, list[dict]],
    pred_tables: list[dict],
    cell_f1: dict[str, float],
) -> dict:
    """1 文書のまたぐ表の採点。

    `gold_tables` は正解の表要素、`gold_grids` は表 id → 格子（`grid_from_elements`）、
    `pred_tables` は出力 JSON の `tables`、`cell_f1` は表 id → 既存の `table_scores` のセル F1。
    """
    uniq = unique_texts(gold_grids)
    pred_texts = [_texts(t.get("grid")) for t in pred_tables]
    rows = []
    for t in gold_tables:
        tid = t["element_id"]
        if tid not in gold_grids:
            continue
        u = uniq.get(tid, set())
        n_frag = sum(1 for p in pred_texts if len(p & u) >= 2) if len(u) >= 2 else None
        rows.append(
            {
                "table_id": tid,
                "span": span_kind(t),
                "n_pages": len(t.get("pages") or []),
                "n_fragments": n_frag,
                "cell_f1": cell_f1.get(tid, 0.0),
            }
        )
    overmerged = 0
    for p in pred_texts:
        hit = [tid for tid, u in uniq.items() if len(u) >= 2 and len(p & u) >= 2]
        if len(hit) >= 2:
            overmerged += 1
    return {"tables": rows, "n_overmerged": overmerged}


def _mean(v: list[float]) -> float:
    return round(sum(v) / len(v), 4) if v else 0.0


def summarize_spans(docs: list[dict]) -> dict:
    """文書別の `span_scores` を集約する。分断度は固有の本文が 2 つ以上ある表だけで数える。"""
    rows = [r for d in docs for r in d["tables"]]
    out: dict = {"n_overmerged": sum(d["n_overmerged"] for d in docs)}
    for k in SPANS:
        sel = [r for r in rows if r["span"] == k]
        frag = [r["n_fragments"] for r in sel if r["n_fragments"] is not None]
        out[k] = {
            "n": len(sel),
            "cell_f1": _mean([r["cell_f1"] for r in sel]),
            "n_measured": len(frag),
            "fragments_mean": _mean([float(x) for x in frag]),
            "n_whole": sum(1 for x in frag if x == 1),
            "n_split": sum(1 for x in frag if x >= 2),
            "n_missing": sum(1 for x in frag if x == 0),
        }
    return out

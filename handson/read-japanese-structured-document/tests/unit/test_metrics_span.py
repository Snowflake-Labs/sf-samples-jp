"""ページ・段をまたぐ表の採点（eval/metrics_span.py）。つながない・正しくつなぐ・誤ってつなぐの対照を持つ。"""

from __future__ import annotations

from jpdocread.eval.metrics_span import span_kind, span_scores, summarize_spans, unique_texts


def grid(rows: list[list[str]]) -> list[dict]:
    return [
        {"row": r, "col": c, "rowspan": 1, "colspan": 1, "text": t, "is_header": r == 0}
        for r, row in enumerate(rows)
        for c, t in enumerate(row)
    ]


HEAD = ["用語", "定義"]
GOLD_A = grid([HEAD, ["甲語", "甲の定義"], ["乙語", "乙の定義"], ["丙語", "丙の定義"]])
GOLD_B = grid([HEAD, ["丁語", "丁の定義"], ["戊語", "戊の定義"]])
GOLD_TABLES = [
    {"element_id": "A", "kind": "table", "pages": [3, 4], "bboxes": [[0] * 4, [0] * 4]},
    {"element_id": "B", "kind": "table", "pages": [5], "bboxes": [[0] * 4]},
]
GRIDS = {"A": GOLD_A, "B": GOLD_B}
F1 = {"A": 0.5, "B": 1.0}


def pred(rows: list[list[str]], pages: list[int]) -> dict:
    return {"pages": pages, "grid": grid(rows)}


def rows_of(res: dict) -> dict[str, dict]:
    return {r["table_id"]: r for r in res["tables"]}


def test_span_kind():
    assert span_kind({"pages": [3, 4], "bboxes": [1, 2]}) == "page"
    assert span_kind({"pages": [9], "bboxes": [1, 2]}) == "column"
    assert span_kind({"pages": [9], "bboxes": [1]}) == "single"
    assert span_kind({}) == "single"


def test_unique_texts_drop_shared_header():
    """見出しの「用語」「定義」は両方の表にあるので、どちらの表の固有の本文にも入らない。"""
    u = unique_texts(GRIDS)
    assert "用語" not in u["A"] and "定義" not in u["B"]
    assert {"甲語", "丙の定義"} <= u["A"]


def test_split_prediction_counts_two_fragments():
    """つながない予測：ページごとの断片が 2 つ → 分断度 2。誤連結は 0。"""
    preds = [
        pred([HEAD, ["甲語", "甲の定義"]], [3]),
        pred([HEAD, ["乙語", "乙の定義"], ["丙語", "丙の定義"]], [4]),
        pred([HEAD, ["丁語", "丁の定義"], ["戊語", "戊の定義"]], [5]),
    ]
    res = span_scores(GOLD_TABLES, GRIDS, preds, F1)
    assert rows_of(res)["A"]["n_fragments"] == 2
    assert rows_of(res)["B"]["n_fragments"] == 1
    assert res["n_overmerged"] == 0


def test_stitched_prediction_counts_one():
    """正しくつないだ予測：分断度 1。"""
    preds = [
        pred([HEAD, ["甲語", "甲の定義"], ["乙語", "乙の定義"], ["丙語", "丙の定義"]], [3, 4]),
        pred([HEAD, ["丁語", "丁の定義"], ["戊語", "戊の定義"]], [5]),
    ]
    res = span_scores(GOLD_TABLES, GRIDS, preds, F1)
    assert rows_of(res)["A"]["n_fragments"] == 1
    assert res["n_overmerged"] == 0


def test_overmerged_prediction_is_counted():
    """誤ってつないだ予測：別々の正解の表 A・B を 1 つにした → 誤連結 1。"""
    preds = [
        pred(
            [HEAD, ["甲語", "甲の定義"], ["乙語", "乙の定義"], ["丙語", "丙の定義"]]
            + [["丁語", "丁の定義"], ["戊語", "戊の定義"]],
            [3, 4, 5],
        )
    ]
    res = span_scores(GOLD_TABLES, GRIDS, preds, F1)
    assert res["n_overmerged"] == 1


def test_missing_prediction_counts_zero():
    res = span_scores(GOLD_TABLES, GRIDS, [], F1)
    assert rows_of(res)["A"]["n_fragments"] == 0


def test_summarize_by_span():
    split = span_scores(
        GOLD_TABLES,
        GRIDS,
        [
            pred([HEAD, ["甲語", "甲の定義"]], [3]),
            pred([HEAD, ["乙語", "乙の定義"], ["丙語", "丙の定義"]], [4]),
            pred([HEAD, ["丁語", "丁の定義"], ["戊語", "戊の定義"]], [5]),
        ],
        F1,
    )
    s = summarize_spans([split])
    assert s["page"] == {
        "n": 1,
        "cell_f1": 0.5,
        "n_measured": 1,
        "fragments_mean": 2.0,
        "n_whole": 0,
        "n_split": 1,
        "n_missing": 0,
    }
    assert s["single"]["n_whole"] == 1 and s["column"]["n"] == 0
    assert s["n_overmerged"] == 0

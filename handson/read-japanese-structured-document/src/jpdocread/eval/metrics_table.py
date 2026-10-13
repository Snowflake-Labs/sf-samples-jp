"""表の採点。

指標は**対にして**出す：
- **セル F1**（順序に鈍感）— `(row, col, text)` の三つ組の集合一致
- **`header_path` 一致率**（構造に敏感）— 各データセルの行見出し列・列見出し列がともに一致

`header_path` は**決定的な導出**であり LLM に出させない（F4：LLM を 2 回呼ばない）。
計画は「SQL で導出」と書いているが、格子はローカル JSON として手元にあり導出は純粋な
論理なので、ここでは Python で導出する。**規則の狙い（LLM に 2 回出させない）は
満たしている。** SQL で書き直しても数値は変わらない。

`is_header` は**入れ子の行見出しを別掲**する（F10 の既知の弱点）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# 比較用の正規化。**格納する本文は正規化しない**（§1.11）。比較層だけで行う。
WS = re.compile(r"[\s\u3000]+")


def norm_cell(s: str | None) -> str:
    """セル本文の比較用正規化。空白を畳み、NFKC を当てる。

    **なぜ NFKC を比較層でだけ当てるか：** 全角/半角の差は組版由来で、セルの値としては
    同一である。一方この正規化を格納側に当てると引用同一性が壊れる（`（1）` と `(1)`）。
    **正規化前と後の両方を報告する**ため、
    呼び出し側で `norm=False` の系列も併せて計算する。
    """
    if s is None:
        return ""
    return WS.sub("", unicodedata.normalize("NFKC", s))


def raw_cell(s: str | None) -> str:
    if s is None:
        return ""
    return WS.sub("", s)


def _expand(grid: list[dict]) -> dict[tuple[int, int], dict]:
    """結合を展開して (row, col) → セル の写像を作る。

    格子は左上セルのみを持つ約束なので、`rowspan`/`colspan` ぶんを埋める。
    採点で位置をそろえるために必要。
    """
    occ: dict[tuple[int, int], dict] = {}
    for c in grid:
        try:
            r0, c0 = int(c["row"]), int(c["col"])
            rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
        except (KeyError, TypeError, ValueError):
            continue
        for dr in range(max(1, rs)):
            for dc in range(max(1, cs)):
                occ.setdefault((r0 + dr, c0 + dc), c)
    return occ


def header_path(grid: list[dict], normalize: bool = True) -> dict[tuple[int, int], tuple]:
    """データセルごとの (行見出し列, 列見出し列) を決定的に導出する。

    gold の `header_path` と同じ形にする：同じ行にあってそのセルより左の見出しセルを
    `row_headers`、同じ列にあってそのセルより上の見出しセルを `col_headers`。
    結合セルは展開後の位置で参照する。
    """
    f = norm_cell if normalize else raw_cell
    occ = _expand(grid)
    if not occ:
        return {}
    max_r = max(r for r, _ in occ)
    max_c = max(c for _, c in occ)
    out: dict[tuple[int, int], tuple] = {}
    for (r, c), cell in occ.items():
        if cell.get("is_header"):
            continue
        rh, seen = [], set()
        for cc in range(0, c):
            h = occ.get((r, cc))
            if h is not None and h.get("is_header"):
                t = f(h.get("text"))
                if t and t not in seen:
                    seen.add(t)
                    rh.append(t)
        ch, seen2 = [], set()
        for rr in range(0, r):
            h = occ.get((rr, c))
            if h is not None and h.get("is_header"):
                t = f(h.get("text"))
                if t and t not in seen2:
                    seen2.add(t)
                    ch.append(t)
        out[(r, c)] = (tuple(rh), tuple(ch))
    _ = (max_r, max_c)
    return out


@dataclass
class TableScore:
    n_gold_cells: int = 0
    n_pred_cells: int = 0
    cell_f1: float = 0.0
    cell_f1_raw: float = 0.0
    pos_text_acc: float = 0.0  # 位置をそろえた上での本文一致率
    header_path_acc: float = 0.0
    # gold の is_header を与えた上での header_path 一致率。
    # 「見出しの文字を読めるか」と「どれが見出しか判定できるか」を分ける（下記参照）。
    header_path_acc_given_isheader: float = 0.0
    is_header_acc: float = 0.0
    nested_row_header_acc: float = 0.0  # F10 の弱点。行見出しが 2 段以上のセルのみ
    n_nested: int = 0
    shape_ok: bool = False  # n_rows/n_cols が一致したか
    truncated: bool = False  # 宣言サイズに対しセルが足りない＝切断の疑い
    notes: list[str] = field(default_factory=list)


def _f1(gold: set, pred: set) -> float:
    if not gold and not pred:
        return 1.0
    if not gold or not pred:
        return 0.0
    tp = len(gold & pred)
    if tp == 0:
        return 0.0
    p, r = tp / len(pred), tp / len(gold)
    return 2 * p * r / (p + r)


def score_table(
    gold_grid: list[dict],
    pred_grid: list[dict],
    gold_shape: tuple[int, int] | None = None,
    pred_shape: tuple[int, int] | None = None,
) -> TableScore:
    s = TableScore(n_gold_cells=len(gold_grid), n_pred_cells=len(pred_grid))
    g_exp, p_exp = _expand(gold_grid), _expand(pred_grid)

    # セル F1：位置と本文の三つ組。順序に鈍感な指標。
    gset = {(r, c, norm_cell(x.get("text"))) for (r, c), x in g_exp.items()}
    pset = {(r, c, norm_cell(x.get("text"))) for (r, c), x in p_exp.items()}
    s.cell_f1 = _f1(gset, pset)
    s.cell_f1_raw = _f1(
        {(r, c, raw_cell(x.get("text"))) for (r, c), x in g_exp.items()},
        {(r, c, raw_cell(x.get("text"))) for (r, c), x in p_exp.items()},
    )

    # 位置をそろえた本文一致率：位置が合っている前提で「読めているか」だけを見る
    common = set(g_exp) & set(p_exp)
    if common:
        s.pos_text_acc = sum(
            1 for k in common if norm_cell(g_exp[k].get("text")) == norm_cell(p_exp[k].get("text"))
        ) / len(common)
        s.is_header_acc = sum(
            1 for k in common if bool(g_exp[k].get("is_header")) == bool(p_exp[k].get("is_header"))
        ) / len(common)

    # header_path：データセルごとに行見出し列・列見出し列がともに一致するか
    gh, ph = header_path(gold_grid), header_path(pred_grid)
    if gh:
        s.header_path_acc = sum(1 for k, v in gh.items() if ph.get(k) == v) / len(gh)
        nested = [k for k, v in gh.items() if len(v[0]) >= 2]
        s.n_nested = len(nested)
        if nested:
            s.nested_row_header_acc = sum(1 for k in nested if ph.get(k) == gh[k]) / len(nested)

    # **2 つの能力を分ける。** header_path が 0 になる表の多くは、本文は完全に読めて
    # いるのに `is_header` の判定だけが違う（実測：cell F1 1.000 かつ header_path 0.000
    # が 58 表中 18 表。誤りは最左列に集中し、1 セルの誤判定がその行の row_headers を
    # すべて消す）。そこで **gold の is_header を予測格子に与え直した**条件でも測る。
    # 差が「見出しの判定」に、残差が「見出しの文字の読み」に帰属する。
    if gh:
        g_flag = {(r, c): bool(x.get("is_header")) for (r, c), x in g_exp.items()}
        patched = []
        for cell in pred_grid:
            try:
                key = (int(cell["row"]), int(cell["col"]))
            except (KeyError, TypeError, ValueError):
                continue
            if key in g_flag:
                cell = dict(cell)
                cell["is_header"] = g_flag[key]
            patched.append(cell)
        ph2 = header_path(patched)
        s.header_path_acc_given_isheader = sum(1 for k, v in gh.items() if ph2.get(k) == v) / len(
            gh
        )

    if gold_shape and pred_shape:
        s.shape_ok = tuple(gold_shape) == tuple(pred_shape)
    if pred_shape and pred_shape[0] * pred_shape[1] > 0:
        # 宣言した論理サイズを覆えていないならセル列が途中で切れている疑い（F12）
        covered = len(p_exp)
        if covered < 0.9 * pred_shape[0] * pred_shape[1]:
            s.truncated = True
            s.notes.append(
                f"宣言 {pred_shape[0]}x{pred_shape[1]} に対し覆うセル {covered}。切断の疑い"
            )
    return s

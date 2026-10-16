"""図の採点。

**採点はラベルで行う。id では行わない**（F9）。モデルは独自 id（`step1`）を発明するので、
id 基準の比較は偽の失敗を報告する。

指標は対にして出す：
- **ノード F1**（ラベル集合）— 文字が読めているか
- **辺 F1**（始点ラベル, 終点ラベル, 辺ラベル の三つ組）— **構造を理解したか**
- **経路 F1**（根→葉のラベル列）— 経路質問（`figure_path` 188 問）に直結

さらに **図ごとの交差辺の本数を併記**する（F11：難易度の説明変数はサイズではなく交差）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def nlabel(s: str | None) -> str:
    """ラベルの比較用正規化。空白を落として NFKC。"""
    if s is None:
        return ""
    return "".join(unicodedata.normalize("NFKC", s).split())


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


def edge_triples(nodes: list[dict], edges: list[dict]) -> set[tuple[str, str, str]]:
    by_id = {n.get("id"): nlabel(n.get("label")) for n in nodes}
    out = set()
    for e in edges:
        a, b = by_id.get(e.get("from")), by_id.get(e.get("to"))
        if a is None or b is None:
            continue
        out.add((a, b, nlabel(e.get("label"))))
    return out


def node_labels(nodes: list[dict]) -> set[str]:
    return {nlabel(n.get("label")) for n in nodes if nlabel(n.get("label"))}


def _pos(nodes: list[dict]) -> dict[str, tuple[float, float]]:
    """gold の図ノードから位置を取れる場合のみ使う（交差辺の数え上げ用）。"""
    out = {}
    for n in nodes:
        bb = (n.get("bboxes") or [None])[0] if isinstance(n.get("bboxes"), list) else None
        if bb:
            out[n.get("id")] = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    return out


def _seg_cross(p1, p2, p3, p4) -> bool:
    def o(a, b, c):
        v = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
        return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)

    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return d1 != d2 and d3 != d4


def count_crossings(nodes: list[dict], edges: list[dict]) -> int | None:
    """辺を直線と見なして交差数を数える。**位置が取れないときは `None` を返す。**

    **完全な幾何ではない**（実際の配線は折れ線）。それでも
    「交差が多い図か少ない図か」の説明変数としては十分である（F11）。

    **T6 の結論：交差は測定できる。ただし PILOT には交差図が 1 件も無い。**

    位置は `figure` 要素ではなく **`figure_node` 要素**（`element_id` が
    `{fig_id}::{node_id}`）の bbox にある。`e4_figures.gold_graph` がこれを
    貼って渡す。`figure` 要素だけを見ると座標が無いように見えるので注意する。

    実測（ALL 39 文書・図 126 件、`gold_graph` 経由）:

    - 座標が全く取れない図 **0 件**。したがって `None` は実際には出ない。
    - 交差 0 の図 **113 件**、交差 >0 の図 **13 件**（10.3%）。
    - 交差数の分布は 1〜285 と非常に偏る（75 が 3 件、108 が 2 件、285 が 1 件）。
    - **PILOT の図 24 件は全て交差 0。** よって `edge_f1_crossed` が null に
      なるのは指標の不具合ではなく**標本構成**である。F11 を実際に測るには
      図の標本を PILOT の外に広げる必要があり、これは追加課金を伴う。

    **注意：交差数は過小評価である。** bbox を持つノードは図あたり中央値 60%
    しかなく、位置の無いノードに繋がる辺は線分に変換されず落ちる。
    絶対数ではなく「交差ありか否か」の層別にのみ使うこと。

    **`None` を 0 に畳んではならない。** 0 は「交差が無い」、`None` は
    「数えられていない」であり、畳むと全図が plain 群に入って
    「交差は難所ではない」という誤った読みを生む。
    """
    pos = _pos(nodes)
    if not pos:
        return None
    segs = []
    for e in edges:
        a, b = pos.get(e.get("from")), pos.get(e.get("to"))
        if a and b:
            segs.append((a, b))
    n = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            (a1, a2), (b1, b2) = segs[i], segs[j]
            if len({a1, a2, b1, b2}) < 4:
                continue  # 端点を共有する辺は交差に数えない
            if _seg_cross(a1, a2, b1, b2):
                n += 1
    return n


def paths_labels(nodes: list[dict], edges: list[dict], max_depth: int = 8) -> set[tuple[str, ...]]:
    """根→葉の経路をラベル列の集合にする。`read.figures.paths_from_graph` と同じ規則。"""
    by_id = {n.get("id"): nlabel(n.get("label")) for n in nodes}
    adj: dict[str, list[str]] = {}
    indeg: dict[str, int] = {i: 0 for i in by_id}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a in by_id and b in by_id:
            adj.setdefault(a, []).append(b)
            indeg[b] = indeg.get(b, 0) + 1
    out: set[tuple[str, ...]] = set()

    def walk(node, acc, seen):
        if len(acc) > max_depth:
            return
        nxt = [c for c in adj.get(node, []) if c not in seen]
        if not nxt:
            if len(acc) > 1:
                out.add(tuple(by_id[x] for x in acc))
            return
        for c in nxt:
            walk(c, acc + [c], seen | {c})

    for r in [i for i in by_id if indeg.get(i, 0) == 0]:
        walk(r, [r], {r})
    return out


@dataclass
class FigureScore:
    n_gold_nodes: int = 0
    n_pred_nodes: int = 0
    n_gold_edges: int = 0
    n_pred_edges: int = 0
    node_f1: float = 0.0
    edge_f1: float = 0.0
    path_f1: float = 0.0
    role_acc: float = 0.0  # ラベルで対応づいたノードの role 一致率
    n_crossings_gold: int | None = None  # None は「測定不能」（T6）。0 と区別する。
    decl_matches: bool = False  # 宣言カウントと実出力数の一致（切断検出。幻覚は捕まえない）
    notes: list[str] = field(default_factory=list)


def score_figure(
    gold_nodes: list[dict],
    gold_edges: list[dict],
    pred_nodes: list[dict],
    pred_edges: list[dict],
    decl: tuple[int, int] | None = None,
) -> FigureScore:
    s = FigureScore(
        n_gold_nodes=len(gold_nodes),
        n_pred_nodes=len(pred_nodes),
        n_gold_edges=len(gold_edges),
        n_pred_edges=len(pred_edges),
    )
    gl, pl = node_labels(gold_nodes), node_labels(pred_nodes)
    s.node_f1 = _f1(gl, pl)
    s.edge_f1 = _f1(edge_triples(gold_nodes, gold_edges), edge_triples(pred_nodes, pred_edges))
    s.path_f1 = _f1(paths_labels(gold_nodes, gold_edges), paths_labels(pred_nodes, pred_edges))
    grole = {nlabel(n.get("label")): (n.get("role") or "") for n in gold_nodes}
    prole = {nlabel(n.get("label")): (n.get("role") or "") for n in pred_nodes}
    common = set(grole) & set(prole)
    if common:
        s.role_acc = sum(1 for k in common if grole[k] == prole[k]) / len(common)
    s.n_crossings_gold = count_crossings(gold_nodes, gold_edges)
    if decl:
        s.decl_matches = decl == (len(pred_nodes), len(pred_edges))
        if not s.decl_matches:
            s.notes.append(
                f"宣言 {decl} に対し実出力 ({len(pred_nodes)}, {len(pred_edges)})。切断の疑い"
            )
    return s

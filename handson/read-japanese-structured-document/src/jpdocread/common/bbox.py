"""矩形（PDF の pt・上原点の `[x0, top, x1, bottom]`）の計算（本ハンズオンで追加）。

自前のモジュール（採点の図の領域・S30 の max_tokens 見積もり）で共有する。移植した `eval/evaluate.py`・
`read/integrate.py`・`read/geometry.py` にも同じ式の関数があるが、移植元の形を保つためそのまま残す（DECISIONS J-033）。
"""

from __future__ import annotations

from collections.abc import Sequence

Box = Sequence[float]


def area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def overlap_area(a: Box, b: Box) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def overlap_of_smaller(a: Box, b: Box) -> float:
    """交差 ÷ 小さい方の面積。小さい要素が大きい領域に収まっているかを測る（面積 0 は 1e-6 で割る）。"""
    return overlap_area(a, b) / max(min(area(a), area(b)), 1e-6)


def contains(outer: Box, inner: Box, tol: float = 0.0) -> bool:
    """`inner` が `outer` に収まるか（各辺 `tol` pt の余裕を見る）。"""
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )

"""表ブロックから参照表（キー → 値）を決定的に読む。

キーの書式：第1級 / 1級 / 24か月まで / 1年まで / {const:…}まで / 2年以下 / 3日以上 など。
値の書式：100% / 90％ / 3万円 / 5,000円 など。値は numparse で解決し、割合は百分率の整数にする。
読めないセルは TableReadError（黙って捨てない）。
"""

from __future__ import annotations

import re

from ..common import numparse as N
from .policy_index import PolicyIndex


class TableReadError(ValueError):
    pass


def _key(text: str) -> int:
    s = re.sub(r"(まで|以下|未満|以上|を超える|超)$", "", text.strip())
    q = N.parse(s)
    if q.unit == "UNLIMITED":
        raise TableReadError(f"unlimited key: {text!r}")
    v = q.value
    if not isinstance(v, int):
        raise TableReadError(f"non-integer key: {text!r}")
    return v


def _val(text: str) -> int:
    q = N.parse(text)
    if not isinstance(q.value, int):
        raise TableReadError(f"non-integer value: {text!r}")
    return q.value


def grid_texts(ix: PolicyIndex, block_id: str) -> list[list[str]]:
    b = ix.by_id.get(block_id)
    if not b or b.get("type") != "table":
        raise TableReadError(f"not a table: {block_id}")
    return [[ix.expand(c.get("text")) for c in row] for row in b["grid"]]


def read_rows(
    ix: PolicyIndex,
    block_id: str,
    *,
    key_col: int | None = None,
    value_col: int | None = None,
    key_row: int | None = None,
    value_row: int | None = None,
) -> list[list[int]]:
    g = grid_texts(ix, block_id)
    if key_row is not None:
        keys, vals = g[key_row][1:], g[value_row][1:]
    else:
        body = g[1:]
        keys = [r[key_col] for r in body]
        vals = [r[value_col] for r in body]
    try:
        return [[_key(k), _val(v)] for k, v in zip(keys, vals, strict=True)]
    except (N.NumParseError, ValueError) as e:
        raise TableReadError(f"{block_id}: {e}") from e


def auto_layout(ix: PolicyIndex, block_id: str) -> dict:
    """表の向きと列を推定する：数値のキーと数値の値が取れる配置のうち、行数が最も多いものを選ぶ（2 行以上）。

    横向きの表（1 行目がキー、2 行目が値）を縦に読むと本文が 1 行しかないので、行数で比べて取り違えを防ぐ
    （横向きの逓減率表を [[40, 30]] と読んだ不具合への対策）。
    """
    g = grid_texts(ix, block_id)
    cands: list[tuple[int, int, dict]] = []
    if len(g) >= 2:
        ncol = len(g[0])
        for kc in range(ncol):
            for vc in range(ncol - 1, -1, -1):
                if kc == vc:
                    continue
                try:
                    n = len(read_rows(ix, block_id, key_col=kc, value_col=vc))
                    cands.append((n, 1, {"key_col": kc, "value_col": vc}))
                except (TableReadError, IndexError):
                    pass
        for kr in range(len(g)):
            for vr in range(len(g)):
                if kr == vr:
                    continue
                try:
                    n = len(read_rows(ix, block_id, key_row=kr, value_row=vr))
                    cands.append((n, 0, {"key_row": kr, "value_row": vr}))
                except (TableReadError, IndexError):
                    pass
    cands = [c for c in cands if c[0] >= 2]
    if not cands:
        raise TableReadError(f"{block_id}: no numeric key/value layout with 2+ rows")
    cands.sort(key=lambda c: (-c[0], -c[1]))
    return cands[0][2]

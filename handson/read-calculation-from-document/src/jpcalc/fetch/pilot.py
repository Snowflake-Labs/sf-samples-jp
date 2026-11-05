"""pilot と few-shot 用（shots）の文書の選定（予測側。公開索引の列だけを使う）。

DEV の PDF から、層（種目・契約種別）と体裁をなるべく広く覆うように選ぶ。並びは `sha256(salt + pdf_id)` の
順で決定的にする。shots は pilot と base を共有しない DEV の文書から、pilot と別の層を優先して選ぶ。
正解に由来する列（パターン・ルール数など）は使わない。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from .adapters import PdfRef

PILOT_SALT = "jpcalc-pilot-v1:"


def _order(refs: Sequence[PdfRef]) -> list[PdfRef]:
    return sorted(refs, key=lambda r: hashlib.sha256((PILOT_SALT + r.pdf_id).encode()).hexdigest())


def _greedy(cands: list[PdfRef], n: int, *, avoid_strata: set[str] = frozenset()) -> list[PdfRef]:
    out: list[PdfRef] = []
    strata, styles, bases = set(avoid_strata), set(), set()
    while len(out) < n:
        rest = [r for r in cands if r not in out and r.split_group not in bases]
        if not rest:
            break
        # 新しい層 → 新しい体裁 → 並び順 の優先で 1 件ずつ選ぶ（同じ base は 1 件だけ）
        best = min(rest, key=lambda r: (r.stratum in strata, r.style in styles, cands.index(r)))
        out.append(best)
        strata.add(best.stratum)
        styles.add(best.style)
        bases.add(best.split_group)
    return out


def pick(dev_refs: Sequence[PdfRef], *, n_pilot: int, n_shots: int) -> tuple[list[str], list[str]]:
    cands = _order(dev_refs)
    pilot = _greedy(cands, n_pilot)
    pilot_bases = {r.split_group for r in pilot}
    shot_cands = [r for r in cands if r.split_group not in pilot_bases]
    shots = _greedy(shot_cands, n_shots, avoid_strata={r.stratum for r in pilot})
    return [r.pdf_id for r in pilot], [r.pdf_id for r in shots]

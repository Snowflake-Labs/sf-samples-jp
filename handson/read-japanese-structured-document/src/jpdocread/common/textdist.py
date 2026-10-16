"""2 つの**予測**の隔たりを測る。gold は関与しない。

評価側の `cer()` とは意図が違うので別に置く。
  * `cer(pred, gold)` は gold を分母に置く **非対称**な誤り率。正解が要る。
  * ここの `disagreement()` は対等な 2 者の距離なので **対称**（長い方を分母にする）。

予測コードが評価コードを import することは禁じられている（`common/guard.py`）ので、
本文パスで使う距離はこちらを使う。
"""

from __future__ import annotations

from rapidfuzz.distance import Levenshtein


def disagreement(a: str, b: str) -> float:
    """0.0（同一）〜1.0（全く違う）。長い方の字数で正規化するので対称。"""
    if not a and not b:
        return 0.0
    return Levenshtein.distance(a, b) / max(len(a), len(b))

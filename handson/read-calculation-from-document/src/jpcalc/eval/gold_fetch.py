"""正解の取得（評価側。--eval のときだけ使う）。

評価用の allow-list はコーパス設定の paths.gold から作り、予測用の取得とは別の置き場所に置く。
評価用のパターンが予測用の allow-list（PDF）と重なったら止める。完全な索引は取得しない。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..fetch.adapters import match_path, render
from .gold import write_ids


class GoldFetchError(ValueError):
    """評価用の allow-list が不正。"""


def gold_patterns(cfg, doc_ids: Sequence[str]) -> list[str]:
    pats = [render(t, doc_id=d) for d in doc_ids for t in cfg.paths.gold]
    if cfg.index.file in pats:
        raise GoldFetchError("評価用の allow-list に完全な索引が入っている")
    return pats


def check_disjoint(gold: Sequence[str], predict_allow: Sequence[str]) -> None:
    bad = [g for g in gold if g.endswith(".pdf") or any(match_path(g, a) for a in predict_allow)]
    if bad:
        raise GoldFetchError(f"評価用のパターンが予測用の allow-list と重なる: {bad[:5]}")


def fetch_gold(
    cfg, source, doc_ids: Sequence[str], dest: Path, predict_allow: Sequence[str]
) -> list[Path]:
    pats = gold_patterns(cfg, doc_ids)
    check_disjoint(pats, predict_allow)
    got = source.fetch_patterns(dest, pats)
    # 取得元のパターンの解釈（`*` が / をまたぐ）で PDF が混ざっていないこと
    pdfs = [p for p in got if p.suffix == ".pdf"]
    if pdfs:
        raise GoldFetchError(f"評価用の取得に PDF が混ざった: {[str(p) for p in pdfs[:3]]}")
    # 固定 revision の照合値を記録する（評価のときに再計算して突き合わせる。取得元が持たなければ記録しない）
    rels = [p.relative_to(dest).as_posix() for p in got]
    ids = source.file_ids(rels) if hasattr(source, "file_ids") else {}
    if ids:
        write_ids(dest, ids)
    return got

"""逆対照（評価側だけ）。評価値を報告する前に、採点の仕組みだけで損失が出ていないことを確かめる。

1. 正解プログラム自身を評価対象として正解テストに渡すと、全ケースに合格する（ハーネスと sandbox の確認）。
2. 正解カードを合成カード（根拠の本文 = 正解の根拠）として対応付け M に与えると、恒等の対応になる。
3. その恒等の対応のアダプタ越しに正解プログラムを採点すると、全ケースに合格する（アダプタと暦の受け渡しの確認）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import match, score
from .gold import Gold


def run_controls(g: Gold) -> dict:
    ref = score.summarize(g, g.doc_id, score.run_pytest(g, g.reference_program()))
    cards = g.task_cards()
    gt = match.gold_evidence(cards, g.answer_key(), g.text_json())
    gen = [dict(c, evidence_text=" ".join(gt[c["function"]])) for c in cards]
    mp = match.build_map(g.doc_id, cards, gt, gen)
    not_identity = match.is_identity(mp, cards)
    with tempfile.TemporaryDirectory(prefix="jpcalc_ctl_") as t:
        ad = Path(t) / "adapter.py"
        src = g.reference_program().read_text(encoding="utf-8")
        ad.write_text(match.adapter_source(src, mp), encoding="utf-8")
        idn = score.summarize(g, g.doc_id, score.run_pytest(g, ad))
    ok = (
        not ref["error"]
        and ref["n_pass"] == ref["n_cases"]
        and not not_identity
        and not idn["error"]
        and idn["n_pass"] == idn["n_cases"]
    )
    return {
        "doc_id": g.doc_id,
        "ok": ok,
        "reference": f"{ref['n_pass']}/{ref['n_cases']}",
        "identity_map": f"{len(cards) - len(not_identity)}/{len(cards)}",
        "identity_adapter": f"{idn['n_pass']}/{idn['n_cases']}",
        "not_identity": not_identity,
        "n_rules": len(cards),
        "n_cases": ref["n_cases"],
    }

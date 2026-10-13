"""T9：大域デコード（位置順ビーム DP）。

**`greedy` を必ず並走させる**（E7b）。差が消えるなら制約が効いていない。
"""

from __future__ import annotations

from jpdocread.read.structure.candidates import Candidate
from jpdocread.read.structure.decode import (
    LAMBDA,
    State,
    _accept_cost,
    decode_for_doc,
    decode_global,
    decode_greedy,
)


def _c(pos: int, kind: str, level: int, num: int, score: float) -> Candidate:
    return Candidate(
        pos=pos,
        page=1 + pos // 50,
        kind=kind,
        level=level,
        num=num,
        label=f"第{num}{kind[0]}",
        title="題名",
        line=f"第{num}条（題名）",
        feats={},
        score=score,
    )


class TestLevelSkipping:
    """**レベルの飛ばしを罰してはならない。** ここを誤ると章が丸ごと落ちる。

    実測：条に節を要求した版では、章を採用すると以降の全条に入れ子違反が付き、
    DP は「章を全部捨てる」方を選んだ。gold の章 1〜4 が消え、再現 1.000 → 0.750。
    """

    def test_article_directly_under_chapter_is_not_penalised(self):
        st = State().with_accept(2, 1)  # 第1章 を開く（節は無い）
        pen, reason, _ = _accept_cost(st, 4, 1, LAMBDA)
        assert pen == 0.0, f"章の直下の条が罰された: {reason}"

    def test_orphan_deep_level_is_penalised(self):
        """逆対照：上位が 1 つも開いていない深いレベルは罰する。"""
        pen, reason, _ = _accept_cost(State(), 4, 1, LAMBDA)
        assert pen > 0 and "orphan" in reason

    def test_chapters_survive_decoding_when_sections_absent(self):
        """節を持たない章構成でも、章が採用され続けること。"""
        cands = [_c(1, "chapter", 2, 1, 1.45)]
        for i, n in enumerate(range(1, 6), start=2):
            cands.append(_c(i, "article", 4, n, 3.5))
        cands.append(_c(9, "chapter", 2, 2, 1.45))
        for i, n in enumerate(range(1, 4), start=10):
            cands.append(_c(i, "article", 4, n, 3.5))
        r = decode_global(cands)
        chapters = sorted(c.num for c in r.accepted if c.kind == "chapter")
        assert chapters == [1, 2], f"章が落ちた: {chapters}"


class TestMonotonicity:
    def test_gap_is_penalised_proportionally(self):
        # **章を先に開くこと。** 開かないと `orphan` が乗って飛びの効果が見えない。
        st = State().with_accept(2, 1).with_accept(4, 1)
        pen1, _, g1 = _accept_cost(st, 4, 2, LAMBDA)
        pen2, _, g2 = _accept_cost(st, 4, 5, LAMBDA)
        assert g1 == 0 and pen1 == 0.0
        assert g2 == 3 and pen2 > pen1, "飛びが罰されていない"

    def test_non_monotonic_is_penalised(self):
        st = State().with_accept(2, 1).with_accept(4, 5)
        pen, reason, _ = _accept_cost(st, 4, 3, LAMBDA)
        assert pen > 0 and "nonmono" in reason

    def test_child_resets_when_parent_advances(self):
        st = State().with_accept(2, 1).with_accept(4, 7)
        st2 = st.with_accept(2, 2)
        assert st2.nums[4] == 0, "親が進んでも子がリセットされていない"


class TestGlobalVsGreedy:
    """E7b：差が消えるなら制約が効いていない。"""

    def test_global_rejects_a_low_scoring_violator_that_greedy_takes(self):
        cands = [
            _c(1, "article", 4, 1, 3.5),
            _c(2, "article", 4, 2, 3.5),
            _c(3, "article", 4, 1, 0.2),  # 参照らしい低スコアの非単調候補
            _c(4, "article", 4, 3, 3.5),
        ]
        g = decode_global(cands)
        y = decode_greedy(cands, threshold=0.0)
        assert len(g.accepted) < len(y.accepted), "大域デコードが greedy と同じ集合を返した"
        assert all(c.score > 1.0 for c in g.accepted)

    def test_lambda_zero_reduces_to_accept_everything(self):
        """λ=0 なら罰が無いので全部採る。**実装の健全性の対照。**

        これが成り立たないと、再現の低下が罰由来か実装欠陥か切り分けられない
        （実際この対照で「罰が原因」と特定した）。
        """
        cands = [_c(i, "article", 4, n, 1.0) for i, n in enumerate([3, 1, 2], start=1)]
        r = decode_global(cands, lam={"gap": 0, "toc": 0, "nest": 0, "reset": 0})
        assert len(r.accepted) == 3


class TestOnCorpus:
    def test_global_has_higher_precision_than_greedy_on_life(self):
        """`life` は柱が見出しと同字面なので、制約の効果が最も見えやすい。"""
        g = decode_for_doc("life-0001--life-b5-1col-mincho", "global")
        y = decode_for_doc("life-0001--life-b5-1col-mincho", "greedy")
        assert len(g.accepted) < len(y.accepted)

    def test_decode_is_deterministic(self):
        a = decode_for_doc("auto-0001--nl-a4-2col-mincho", "global")
        b = decode_for_doc("auto-0001--nl-a4-2col-mincho", "global")
        assert a.accepted_keys == b.accepted_keys
        assert a.total_score == b.total_score

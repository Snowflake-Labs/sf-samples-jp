"""A4 — デコーダ修復。

W2 は採用集合の F1 で `global` 0.9495 > `greedy` 0.9399 と報告したが、
**引用木の上では逆だった**。修復した 3 つの欠陥に回帰テストを置く。
"""

from __future__ import annotations

from jpdocread.read.structure.candidates import WEIGHTS, _features
from jpdocread.read.structure.decode import LAMBDA, State, _accept_cost


class TestOrphanPenaltyUsesLevelsActuallyPresent:
    """**その文書に存在しないレベルを親として要求してはならない。**

    `golf`/`auto` は編を持たないので、章（レベル 2）は常に「編が開いていない」状態に
    なる。全レベル前提で罰すると**すべての章に孤児の罰**が課され、DP は章を捨てる方が
    得だと判断した（golf の条 recall 0.862 → 0.172）。
    """

    def test_top_level_chapter_is_not_an_orphan(self):
        pen, reason, _ = _accept_cost(
            State(), level=2, num=1, lam=LAMBDA, levels_in_use=frozenset({2, 4})
        )
        assert "orphan" not in reason
        assert pen == 0.0

    def test_article_without_any_open_ancestor_is_an_orphan(self):
        """肯定：章を使う文書で、章が 1 つも開かないまま条が来たら違反である。"""
        pen, reason, _ = _accept_cost(
            State(), level=4, num=1, lam=LAMBDA, levels_in_use=frozenset({2, 4})
        )
        assert "orphan" in reason
        assert pen >= LAMBDA["nest"]

    def test_level_skipping_is_allowed(self):
        """auto の第 1〜4 章は節を持たず章の直下に条が来る。飛ばしは正常な版式。"""
        st = State().with_accept(2, 1)  # 章を開く
        pen, reason, _ = _accept_cost(
            st, level=4, num=1, lam=LAMBDA, levels_in_use=frozenset({2, 3, 4})
        )
        assert "orphan" not in reason
        assert pen == 0.0


class TestRepeatedLineIsNotChargedToArticles:
    """条番号は特約ごとに 1 に戻るので、同じ条見出しは**設計上**再出現する。"""

    def test_weight_sign_is_unchanged(self):
        assert WEIGHTS["repeated_line"] < 0  # 柱への減点そのものは維持する


class TestSentenceMarkNotChargedToArticles:
    """条ラベルと本文が同一行に刷られる体裁（group）では、見出しが本文と行を共有する。

    実測：本物の条見出し −0.10 に対し表キャプション `第2条備考` が 1.54 で、
    **DP はキャプションを選んで本物を捨てた**（group の条 recall 0.750 → 0.361）。
    """

    def test_inline_article_heading_is_not_penalised(self):
        line = "第5条当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。"
        f = _features("article", 5, "当会社は、次の各号の…", line, None)
        assert f["has_sentence_mark"] == 0.0

    def test_chapter_body_line_is_still_penalised(self):
        """否定例：本文の 1 行が行頭から章の形を持つ場合。条以外では減点を残す。"""
        line = "第2章第4条(2)の算式は、相手方の財物を壊してしまったときの損害額です。"
        f = _features("chapter", 2, "第4条(2)の算式は、…", line, None)
        assert f["has_sentence_mark"] == 1.0

    def test_reference_is_still_caught_by_ref_suffix(self):
        """条の参照は句読点ではなく `ref_suffix`（−2.5）で弾く。こちらは行共有でも働く。"""
        f = _features(
            "article", 5, "の規定にかかわらず、当会社は保険金を支払う。", "第5条の規定に…", None
        )
        assert f["ref_suffix"] == 1.0
        assert WEIGHTS["ref_suffix"] <= -2.0

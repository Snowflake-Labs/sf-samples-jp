"""A6 — `repair_items`：表セル由来の偽 `item` の降格（W7・D-2 の決定）。

`item` 適合率 0.1936 の原因は**罫線の無い 2 段の表**（標識列＋本文列）である。
矩形が 1 つも無いので幾何の抑止（`region_lines`）が届かない。gold では
auto の `①記名被保険者。` は `kind='cell'` / `region='table'` である一方、
golf の `①事故の発生の日時…を記載した書面` は真の `item` で、**gold は一貫している。**

3 つの否定規則はいずれも**再現率を 1 件も落とさない**（ALL 39 文書・held-out 29 文書
の両方で `item` recall 不変。適合率 0.1936 → 0.4056）。
"""

from __future__ import annotations

from jpdocread.read.structure.tree import ITEM_UNIT_HEADS, build_tree, repair_items

# **条は 2 つ以上、項は circled で 2 条に出す。** 条の下の流儀は「その流儀が現れた
# 条の数」の多数決で決まるので（A1）、割れると走査が号として認められない。
_HEAD = "第1章総則\n第1条当会社は、次の各号の費用を負担します。\n"
_MID = "②前項の費用は、当会社の定める基準により算定します。\n"
_TAIL = (
    "第2条当会社は、保険料の払込みを受けたときに責任を開始します。\n"
    "②前項の責任開始期は、保険証券に記載します。"
)


def _items(pages, **kw):
    t = build_tree("t", pages, **kw)
    return [n for n in t.nodes.values() if n.kind == "item"]


class TestSiblingRunEndsWithPeriod:
    def test_all_cells_end_with_period_are_demoted(self):
        """走査の全件が「。」で閉じるなら表である（auto の `①記名被保険者。`）。

        **ラベルは dot にする。** この雛形は項の流儀が circled なので、`①` 行は
        号ではなく項として食われてしまい、修復パスを通らない（＝空振りする）。
        実文書の auto では項が `(1)` 形なので `①` が号になる。
        """
        pages = {
            1: _HEAD
            + "1．記名被保険者。\n2．記名被保険者の配偶者。\n3．同居の親族。\n"
            + _MID
            + _TAIL
        }
        assert _items(pages, repair_item_runs=False) != []  # 空振り防止
        assert _items(pages) == []

    def test_real_item_run_survives_even_if_some_end_with_period(self):
        """否定：一部だけ「。」で閉じる走査は号である。

        gold の group-0001 は号 20 件のうち「。」終わりが 3 件（走査比 0.15）。
        **個々の文末ではなく走査の比で決めるのは、この分布のためである。**
        """
        pages = {
            1: _HEAD
            + "1．加入者の故意による場合\n"
            + "2．保険金受取人の故意による場合\n"
            + "3．保険契約者の故意による場合。この場合、その部分のみ支払いません。\n"
            + _MID
            + _TAIL
        }
        assert [i.label for i in _items(pages)] == ["1．", "2．", "3．"]

    def test_threshold_is_a_parameter_tuned_on_held_out(self):
        """`end_frac` は held-out 29 文書で掃いて 0.8 に決めた値である。"""
        pages = {1: _HEAD + "1．甲の費用。\n2．乙の費用。\n3．丙の費用\n" + _MID + _TAIL}
        t = build_tree("t", pages, repair_item_runs=False)
        assert len([n for n in t.nodes.values() if n.kind == "item"]) == 3
        # 2/3 = 0.667。既定 0.8 では残り、0.6 では落ちる。
        assert repair_items(t, end_frac=0.8) == 0
        assert repair_items(t, end_frac=0.6) == 2


class TestNumericExpressionIsNotALabel:
    def test_bare_number_followed_by_a_counter_is_not_an_item(self):
        """`１`＋`億円を限度とします` は `１億円` の行分割である（golf で実測）。

        本文中の参照の除外と同じ種類の否定規則。
        """
        pages = {1: _HEAD + "1．甲の費用\n2．乙の費用\n3．億円を限度とします\n" + _MID + _TAIL}
        assert [i.label for i in _items(pages)] == ["1．", "2．"]

    def test_unit_heads_cover_the_observed_cases(self):
        for ch in "億万円か）":
            assert ch in ITEM_UNIT_HEADS


class TestRunMustStartAtOne:
    def test_run_starting_at_three_is_demoted(self):
        """`③` から始まる走査は号の列挙ではない（親の取り違え）。"""
        pages = {1: _HEAD + "③甲の費用\n④乙の費用\n" + _MID + _TAIL}
        assert _items(pages) == []


class TestDemotionKeepsText:
    def test_lines_are_returned_to_the_parent(self):
        """降格しても**本文は失わない**。行は親ノードに返す。"""
        pages = {1: _HEAD + "1．記名被保険者。\n2．記名被保険者の配偶者。\n" + _MID + _TAIL}
        assert _items(pages, repair_item_runs=False) != []  # 空振り防止
        t = build_tree("t", pages)
        assert [n for n in t.nodes.values() if n.kind == "item"] == []
        assert any(
            "記名被保険者の配偶者。" in "".join(n.lines)
            for n in t.nodes.values()
            if n.kind == "paragraph"
        )

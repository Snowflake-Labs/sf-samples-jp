"""H14 で追加した規則の単体テスト（既定はどれも off。off のときは従来と同じであることも確かめる）。

- 構造：空の先行容器の置き換え（`Builder._supersede`）と別表の節の否定規則（`_is_app_sec_prose`）
- 図の領域：曲線の少ない候補を外す（`regions.few_curves`）
- repair_queue：定型の棄却の印（`integrate._resolution`）
"""

from __future__ import annotations

from jpdocread.read.integrate import ROUTINE_REJECTIONS, ReadOptions, _resolution
from jpdocread.read.regions import FIGURE_FEW_CURVES, few_curves
from jpdocread.read.structure.tree import _is_app_sec_prose, build_tree

# 目次の続き（特約名と条の題名だけ）→ 本文 → 別の特約 → 本物の特約、という並び（health-0002 の形を架空の条文で再現）
TOC_THEN_BODY = [
    "第1章用語の定義",
    "第1条（用語の定義）",
    "この約款で用いる用語の意味は次のとおりとします。",
    "骨折補償特約",
    "第1条（この特約の適用条件）",
    "第2条（この特約の給付内容）",
    "別表1区分表",
    "第1区分と割合",
    "通院補償特約",
    "第1条（この特約の適用条件）",
    "この特約は、保険証券に記載がある場合に適用します。",
    "骨折補償特約",
    "第1条（この特約の適用条件）",
    "この特約は、保険証券に記載がある場合に適用します。",
    "第2条（この特約の給付内容）",
    "当会社は、給付金を支払います。",
    "別表1区分表",
    "第1区分と割合",
    "1．区分は下表のとおりとします。",
]


def _tree(lines: list[str], on: bool):
    return build_tree("t", {1: "\n".join(lines)}, supersede_empty_upper=on)


def _articles(t) -> list[str]:
    return [n.citation for n in t.of_kind("article")]


class TestSupersedeEmptyUpper:
    def test_off_keeps_previous_behaviour(self):
        """off：本物の `骨折補償特約` は重複として本文になり、その条は直前の `通院補償特約` に入る（従来の誤り）。"""
        t = _tree(TOC_THEN_BODY, on=False)
        assert len(t.of_kind("rider")) == 2
        assert "通院補償特約 第2条" in _articles(t)

    def test_on_reopens_real_rider(self):
        """on：空の先行容器を取り除き、本物の見出しで開き直す。条は正しい特約に付く。"""
        t = _tree(TOC_THEN_BODY, on=True)
        assert _articles(t) == [
            "第1章 第1条",
            "通院補償特約 第1条",
            "骨折補償特約 第1条",
            "骨折補償特約 第2条",
        ]
        assert [n.citation for n in t.of_kind("rider")] == ["通院補償特約", "骨折補償特約"]
        assert [n.citation for n in t.of_kind("appendix")] == ["別表1"]
        assert any("空の先行容器を置き換え: rider 骨折補償特約" in r for r in t.rejected)

    def test_superseded_nodes_are_recorded(self):
        """取り除いた容器は `Tree.superseded` に残る（2 回目の組み立ての抑止区間に使う）。"""
        t = _tree(TOC_THEN_BODY, on=True)
        assert sorted(n.label for n, _ in t.superseded) == ["別表1", "骨折補償特約"]

    def test_running_head_of_open_rider_is_not_reopened(self):
        """柱：いま開いている特約と同名の行は置き換えない（従来どおり 1 つ）。"""
        t = _tree(["弁護士費用特約", "第1条（適用条件）", "弁護士費用特約", "本文。"], on=True)
        assert len(t.of_kind("rider")) == 1

    def test_container_with_body_is_not_replaced(self):
        """先に開いた容器に本文があれば置き換えない（本文を失わないため）。"""
        lines = [
            "骨折補償特約",
            "第1条（この特約の適用条件）",
            "この特約は、保険証券に記載がある場合に適用します。",
            "通院補償特約",
            "第1条（この特約の適用条件）",
            "この特約は、乙の場合に適用します。",
            "骨折補償特約",
            "第1条（この特約の適用条件）",
            "本文。",
        ]
        t = _tree(lines, on=True)
        assert [n.citation for n in t.of_kind("rider")] == ["骨折補償特約", "通院補償特約"]
        assert not t.superseded


class TestAppendixSectionProse:
    def test_real_headings_pass(self):
        for s in ("第1区分と割合", "第２判定の時期および方法", "第1区分の表"):
            assert not _is_app_sec_prose(s)

    def test_table_rows_and_sentences_are_rejected(self):
        for s in (
            "第１区分座る、立つ、歩くのいずれについても常に他人の該当する",
            "第３区分に該当するかどうかは、加入の時に届け出た業務の内容を基準として判定します。",
        ):
            assert _is_app_sec_prose(s)

    def test_only_with_flag(self):
        """off では別表の中の文の行も従来どおり節として開く。"""
        lines = [
            "別表1区分表",
            "第1区分と割合",
            "第3区分に該当するかどうかは、届け出た内容で判定します。",
        ]
        off = [n.label for n in _tree(lines, on=False).of_kind("appendix_section")]
        on = [n.label for n in _tree(lines, on=True).of_kind("appendix_section")]
        assert off == ["第1", "第3"]
        assert on == ["第1"]


class TestFewCurves:
    BOX = [0.0, 0.0, 100.0, 100.0]

    def test_range(self):
        assert FIGURE_FEW_CURVES == (1, 4)

    def test_zero_curves_are_kept(self):
        """曲線 0 本（罫線だけの表・マトリクス図）は外さない。"""
        assert not few_curves(self.BOX, [])

    def test_one_to_four_are_dropped(self):
        for n in (1, 4):
            assert few_curves(self.BOX, [(50.0, 50.0)] * n)

    def test_five_or_more_are_kept(self):
        assert not few_curves(self.BOX, [(50.0, 50.0)] * 5)

    def test_outside_curves_are_not_counted(self):
        assert not few_curves(self.BOX, [(150.0, 50.0)] * 3)


class TestRoutineRepairs:
    def test_off_is_open(self):
        assert _resolution("p2 目次行: 第1章 5", False) == "open"

    def test_routine_reasons(self):
        for r in ROUTINE_REJECTIONS:
            assert _resolution(f"p3 {r}: 第1章総則", True) == "routine"

    def test_other_reasons_stay_open(self):
        for loc in ("p4 大域デコードが非採用: 第2条", "item 第1章 第1条 ①: 表セル由来として降格"):
            assert _resolution(loc, True) == "open"


def test_read_options_defaults_are_off():
    o = ReadOptions()
    assert (o.supersede_empty_upper, o.filter_figure_regions, o.label_routine_repairs) == (
        False,
        False,
        False,
    )

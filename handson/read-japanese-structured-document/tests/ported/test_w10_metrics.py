"""W10 — §6.1 で実装した指標と、その過程で見つかった 2 つの規則の誤りのテスト。

**新しい指標には必ず退化ケースの対照を置く**。
全一致で 0、全不一致で 1 になることを確認しないと、指標は静かに壊れる
（W7 で「無くなったこと」を主張して空振りで通るテストを 2 件書いた反省）。

**正規表現は肯定例と否定例を対で書く**。
`RE_APP_SEC` / `JYUSETSU_BADGES` の両方について対を置いた。
"""

from __future__ import annotations

import pytest

from jpdocread.eval.metrics_structure import (
    _boundaries,
    _flat,
    _postorder,
    tree_edit_distance,
)
from jpdocread.eval.metrics_text import bag_cer, cer
from jpdocread.read.structure.tree import (
    JYUSETSU_BADGES,
    RE_APP_SEC,
    RE_APP_SEC_EXCLUDE,
    Builder,
)

# --------------------------------------------------------------- bag-CER


def test_bag_cer_identical_is_zero():
    assert bag_cer("第1条保険金", "第1条保険金") == 0.0


def test_bag_cer_ignores_order_but_cer_does_not():
    """**bag-CER の存在理由。** 並べ替えだけでは 0、CER は 0 でない。

    これが読み順の誤り（2 段組）と文字の読み取りの誤りを分離する（U-3.1）。
    """
    gold, pred = "あいうえお", "うえおあい"
    assert bag_cer(pred, gold) == 0.0
    assert cer(pred, gold) > 0.0


def test_bag_cer_full_mismatch_is_one_like_cer():
    """**置換を 1 と数える。** 対称差の和にすると 2.0 になり CER と並べられない。"""
    assert bag_cer("かきくけこ", "あいうえお") == pytest.approx(1.0)
    assert cer("かきくけこ", "あいうえお") == pytest.approx(1.0)


def test_bag_cer_counts_insertions_and_deletions_separately():
    # 挿入のみ（gold 3 字に 3 字足す）→ max(3, 0)/3
    assert bag_cer("あいうかきく", "あいう") == pytest.approx(1.0)
    # 削除のみ
    assert bag_cer("あ", "あいう") == pytest.approx(2 / 3)


def test_bag_cer_empty_gold():
    assert bag_cer("", "") == 0.0
    assert bag_cer("あ", "") == 1.0


# --------------------------------------------------------------- nTED


def test_tree_edit_distance_identical_is_zero():
    lab = {"a": ("chapter", "第1章"), "b": ("article", "第1条")}
    t1 = _postorder({"a": ["b"]}, ["a"], lab)
    t2 = _postorder({"a": ["b"]}, ["a"], lab)
    assert tree_edit_distance(t1, t2) == 0


def test_tree_edit_distance_one_rename_is_one():
    t1 = _postorder({"a": ["b"]}, ["a"], {"a": ("chapter", "第1章"), "b": ("article", "第1条")})
    t2 = _postorder({"a": ["b"]}, ["a"], {"a": ("chapter", "第1章"), "b": ("article", "第2条")})
    assert tree_edit_distance(t1, t2) == 1


def test_tree_edit_distance_one_deletion_is_one():
    lab = {"a": ("chapter", "第1章"), "b": ("article", "第1条")}
    t1 = _postorder({"a": ["b"]}, ["a"], lab)
    t2 = _postorder({}, ["a"], {"a": ("chapter", "第1章")})
    assert tree_edit_distance(t1, t2) == 1


def test_tree_edit_distance_is_symmetric():
    lab1 = {"a": ("chapter", "第1章"), "b": ("article", "第1条"), "c": ("paragraph", "(1)")}
    t1 = _postorder({"a": ["b"], "b": ["c"]}, ["a"], lab1)
    t2 = _postorder({"a": ["b"]}, ["a"], {"a": ("chapter", "第1章"), "b": ("article", "第1条")})
    assert tree_edit_distance(t1, t2) == tree_edit_distance(t2, t1)


def test_tree_edit_distance_empty_tree_is_size_of_other():
    """**空の木を出しただけで良い数値が出てはならない。**

    正規化を `max(|gold|, |pred|)` にしている理由がこれである（和にすると 0.5 に収まる）。
    """
    t1 = _postorder({"a": ["b"]}, ["a"], {"a": ("chapter", "第1章"), "b": ("article", "第1条")})
    empty = _postorder({}, [], {})
    d = tree_edit_distance(t1, empty)
    assert d == len(t1) - 1  # 仮想根同士は一致するので実ノード数ぶん


# --------------------------------------------------------------- 境界


def test_boundaries_marks_owner_changes_only():
    assert _boundaries(["A", "A", "B", "B", "C"]) == [0, 1, 0, 1]


def test_boundaries_all_same_has_no_boundary():
    assert _boundaries(["A"] * 4) == [0, 0, 0]


# --------------------------------------------------------------- 平坦化


def test_flat_normalizes_width_and_drops_space():
    assert _flat("第１章　総則") == _flat("第1章 総則")


# --------------------------------------------------------------- RE_APP_SEC（W10 の訂正）


@pytest.mark.parametrize(
    "line",
    [
        "第1等級と支払割合",  # 空白が落ちた形（**実際に届く形**）
        "第1　等級と支払割合",  # 印刷面の形
        "第2既経過期間に応じる短期率",
    ],
)
def test_re_app_sec_matches_forms_that_actually_arrive(line):
    """**肯定例。** 元は `[　 ]+` だったため空白なしの形に一致せず、
    39 文書すべてで `appendix_section` が 1 件も出なかった（gold 77 件）。"""
    assert RE_APP_SEC.match(line)
    assert not RE_APP_SEC_EXCLUDE.match(line)


@pytest.mark.parametrize(
    "line",
    [
        "第1級両眼の視力を全く失ったもの",  # 等級表の行（助数詞 `級`）
        "第12級局部に強い神経症状が続くもの",
        "第2章保険金の支払",
        "第3条用語の定義",
        "第1節総則",
        "第2編普通保険約款",
        "第1項の規定にかかわらず",
        "第2号に定める場合",
    ],
)
def test_re_app_sec_exclude_rejects_counters_and_structure(line):
    """**否定例。** 空白必須を外したぶん、助数詞と構造接尾辞を明示的に外す。

    `級` を入れ忘れると `auto-0001` に `第1級`〜`第12級` の
    **12 件の偽 `appendix_section`** が生える（実測）。
    """
    assert RE_APP_SEC_EXCLUDE.match(line)


# --------------------------------------------------------------- jyusetsu の標識（W10）


def _jyusetsu_pages(badge: bool) -> dict[int, str]:
    r"""`2` 章 → `(2)` 節 → `②` 条 → 号 `①②③④` の最小例。

    **号の走査の 3 番目が条番号の期待値（3）と衝突する**のが元の誤りの機構である。

    **行に空白を入れてはならない。** 文法の正規表現は `^(番号)(\S.*)$` であり、
    行の供給元（`pdfplumber` の行結合）は空白を落とす。印刷面の
    `2　契約締結前…` をそのまま書くと一致せず、**合成テストだけが通らない**
    という誤った失敗になる（`RE_APP_SEC` で踏んだのと同じ罠。本波で 2 度目）。
    """
    b1 = "契約概要" if badge else ""
    return {
        1: "\n".join(
            [
                "2契約締結前におけるご確認事項",
                "(2)保険期間と保険料",
                f"①保険期間および補償の開始・終了時期{b1}",
                "保険期間は1年間です。",
                f"②保険料の決定の仕組みと払込方法{b1}",
                "保険料は、次の事項によって決まります。",
                "①ご契約タイプおよび保険金額",
                "②運転者年齢条件",
                "③お車の用途車種および型式",
                "④前年までの事故の有無に応じた等級",
            ]
        )
    }


def _build(pages: dict[int, str]):
    b = Builder("synthetic", grammar="jyusetsu")
    return b.build(pages)


def test_jyusetsu_badge_separates_article_from_item():
    """**肯定例。** 標識がある文書では、標識の無い丸数字行は号になる。

    標識なしでは `③`（走査の 3 番目）が `expect_article`（3）と一致して
    条になってしまう。**番号の単調性では原理的に解けない。**
    """
    t = _build(_jyusetsu_pages(badge=True))
    items = sorted(n.label for n in t.nodes.values() if n.kind == "item")
    arts = sorted(n.label for n in t.nodes.values() if n.kind == "article")
    assert items == ["①", "②", "③", "④"], items
    assert arts == ["①", "②"], arts


def test_jyusetsu_without_badges_rule_is_not_applied():
    """**否定例（適用条件の対照）。** 標識を持たない文書では規則を使わない。

    規則の適用条件を**その文書自身の証拠**に結びつけていることを確認する。
    標識が無ければ従来どおり番号の単調性で判定するので、
    `③` は条として採られる（= 規則が発火していない証拠）。
    """
    t = _build(_jyusetsu_pages(badge=False))
    arts = [n.label for n in t.nodes.values() if n.kind == "article"]
    assert "③" in arts, arts


def test_jyusetsu_badges_constant_is_the_statutory_pair():
    assert JYUSETSU_BADGES == ("契約概要", "注意喚起情報")


# --------------------------------------------------------------- 漏出率


def test_leakage_rate_is_zero_when_no_furniture_present(monkeypatch):
    """退化ケース：柱・フッタが無いページでは漏出率 0。"""
    from jpdocread.eval import metrics_structure as ms

    monkeypatch.setattr(
        ms, "furniture_strings", lambda doc_id: {1: {"header": set(), "footer": set()}}
    )
    from jpdocread.read.structure.tree import Node, Tree

    t = Tree(doc_id="x")
    t.add(Node(node_id="p1", kind="paragraph", citation="第1条 (1)", pages=[1], lines=["本文"]))
    lk = ms.leakage("x", t)
    assert lk.rate == 0.0
    assert lk.n_body_nodes == 1


def test_leakage_rate_is_one_when_every_body_node_contains_furniture(monkeypatch):
    """退化ケース：全本文ノードが柱を含めば漏出率 1。"""
    from jpdocread.eval import metrics_structure as ms
    from jpdocread.read.structure.tree import Node, Tree

    monkeypatch.setattr(
        ms, "furniture_strings", lambda doc_id: {1: {"header": set(), "footer": {"S26-2002"}}}
    )
    t = Tree(doc_id="x")
    t.add(
        Node(
            node_id="p1", kind="paragraph", citation="第1条 (1)", pages=[1], lines=["本文S26-2002"]
        )
    )
    t.add(Node(node_id="p2", kind="item", citation="第1条 (1) ①", pages=[1], lines=["S26-2002"]))
    lk = ms.leakage("x", t)
    assert lk.rate == 1.0
    assert lk.footer_leak == 2


# --------------------------------------------------------------- 番号整合性の分離（D-15）


def test_number_violations_split_is_exhaustive():
    """**intrinsic ＋ gold 由来 = 総数** であることを実データで確認する。

    D-15（番号を捏造しない）により、gold 側にも同じ飛びがある違反には目標を置かない。
    **分離が漏れていると「我々の誤り」を過大に数える。**
    """
    from jpdocread.eval.metrics_structure import number_integrity
    from jpdocread.read.structure.tree import build_tree_for_doc

    doc = "auto-0001--nl-a4-2col-mincho"
    r = number_integrity(doc, build_tree_for_doc(doc, decode="greedy"))
    assert (
        r["number_violations_intrinsic"] + r["number_violations_gold_origin"]
        == (r["number_violations"])
    )


def test_gold_number_violations_uses_same_detector_shape():
    """gold 側の違反記述が予測側と同じ形 `"<kind> <citation>: prev → cur"` であること。

    形が違うと `_violation_keys` が一致せず、**すべてが intrinsic に分類されて
    分離が静かに無効になる**（W10 で 159 件の総数しか出せなかったのと同じ失敗）。

    **文書は「gold に実在の飛びがあるもの」を選ぶ。** 元は `auto-0001` を使っていたが、
    そこで gold が引っかかっていたのは**検出器が正当なリセットを違反と数えていたため**で、
    検出器を直した時点で 0 件になった（= テストの前提が古い契約だった）。
    `teikan-0001` の `第3章 第13条: 15 → 13` は印刷面に実在する飛びである。
    """
    from jpdocread.eval.metrics_structure import _violation_keys, gold_number_violations

    v = gold_number_violations("teikan-0001--teikan-a4-1col-mincho")
    assert v, "gold 側に違反が 1 件も無いと、この分離の検証ができない"
    keys = _violation_keys(v)
    assert keys and all(isinstance(k, tuple) and len(k) == 2 and k[0] for k in keys)


def test_number_violations_treats_reset_to_one_as_legitimate():
    """**リセット（`→ 1`）は違反ではない**（D-15 の実装）。

    肯定例と否定例を対で置く：

    - `5 → 1` は章が特約ごとに振り直される正しい体裁 → **違反にしない**
    - `5 → 3` は番号が戻っているが 1 ではない → **違反にする**

    この 1 行を入れる前は gold 自身が 224 回引っかかっていた（ALL 39）。
    **検出器は gold に当てて校正する** — gold が引っかかるなら検出器が誤っている。
    """
    from jpdocread.read.structure.tree import Node, Tree

    def tree_with(labels: list[str]) -> Tree:
        t = Tree(doc_id="synthetic")
        t.add(Node(node_id="root", kind="rider", label="特約"))
        for i, lab in enumerate(labels):
            t.add(
                Node(
                    node_id=f"a{i}",
                    kind="article",
                    label=lab,
                    citation=f"特約 {lab}",
                    parent_id="root",
                )
            )
        return t

    assert tree_with(["第5条", "第1条"]).number_violations() == []
    assert tree_with(["第5条", "第3条"]).number_violations() != []
    assert tree_with(["第1条", "第2条", "第3条"]).number_violations() == []


# --------------------------------------------------------------- 成果物の直接測定（D-14）


def test_deliverable_duplicate_citations_are_counted_separately():
    """**多重集合であることの対照。** 同じ引用を持つ要素が複数あるとき、集合なら 1 件に潰れる。

    `jyusetsu` は段落が条と同じ引用を持つので、ここで潰れると誤り率が楽観側に振れる。
    移植元の `gold_citation_multiset` は S60 の `citation_scores` の中にあるので、同じ数え方をここで組む。
    """
    from collections import Counter

    from jpdocread.eval.evaluate import BODY_KINDS
    from jpdocread.eval.gold import load_elements
    from jpdocread.read.structure.tree import canonical_citation

    c: Counter = Counter()
    for e in load_elements("jyusetsu-0001--jys-a4-1col-gothic"):
        if e.get("node_kind") in BODY_KINDS:
            c[(e["node_kind"], canonical_citation(e.get("citation") or ""))] += 1
    assert max(c.values()) > 1, "同一引用の重複が無いと多重集合の意味が検証できない"
    assert sum(c.values()) > len(c), "多重集合の総数が集合サイズを上回るべき"


# --------------------------------------------------------------- 別表の節：値で終わる行（W11 T29）


@pytest.mark.parametrize(
    "line",
    [
        "第1等級と支払割合",
        "第1既経過期間に応じる短期率",
        "第2等級および支払割合",
    ],
)
def test_app_sec_value_tail_allows_real_section_names(line):
    """**肯定例。** 真の別表の節の見出しは短い名詞句で、値では終わらない。"""
    from jpdocread.read.structure.tree import RE_APP_SEC, RE_APP_SEC_VALUE_TAIL

    assert RE_APP_SEC.match(line)
    assert not RE_APP_SEC_VALUE_TAIL.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "第1級両眼の視力を全く失ったもの、または起居100%",
        "第12級局部に強い神経症状が続くもの9%",
        "第2両眼の視力が著しく低下したもの、また91%",  # `級` が別カラムに分かれた版
        "第1区分全身麻酔を用いて行う手術20万円",
    ],
)
def test_app_sec_value_tail_rejects_table_rows(line):
    """**否定例。** 等級表の行は行末に支払割合・金額が連結される。

    `級` の否定規則（W10）では取り切れなかった —
    **`級` が別カラムに分かれる版では助数詞が行に届かない**（3 番目の例）。
    **助数詞は行結合の仕方で消えるが、値の列は消えない。**
    実測（ALL 39）：偽 38/39 対 正 3/68 で分離し、適合率 0.5981 → 0.9697。
    """
    from jpdocread.read.structure.tree import RE_APP_SEC_VALUE_TAIL

    assert RE_APP_SEC_VALUE_TAIL.search(line)


# --------------------------------------------------------------- 括弧付きは号ではない（W11 T28）


def test_paren_items_are_dropped_not_demoted():
    """**括弧付きラベルの号はノードごと落とし、親の本文に併合する。**

    降格（`kind='paragraph'`）は誤りである。gold の teikan には
    `（１）生命保険業` に対応するノードが**存在しない**（段落内の列挙）。
    降格すると段落の偽陽性になり、実測で段落適合率が 0.9514 → 0.9393 に落ちた。
    """
    from jpdocread.read.structure.tree import Node, Tree, drop_paren_items

    t = Tree(doc_id="synthetic")
    t.add(Node(node_id="a", kind="article", label="第2条", citation="第2条"))
    t.add(
        Node(
            node_id="p",
            kind="paragraph",
            label="",
            citation="第2条",
            parent_id="a",
            lines=["当会社は、次に掲げる事業を営む。"],
        )
    )
    t.add(
        Node(
            node_id="i1",
            kind="item",
            label="（１）",
            citation="第2条 （１）",
            parent_id="p",
            lines=["生命保険業"],
        )
    )
    assert drop_paren_items(t) == 1
    assert "i1" not in t.nodes
    assert [n.kind for n in t.nodes.values()] == ["article", "paragraph"]
    # 本文は失われず親に残る（黙って捨てない）
    assert "生命保険業" in t.nodes["p"].text


def test_circled_and_dot_items_survive():
    """**否定例。** 丸数字・数字ドットの号は落とさない（gold の号 170 件はこの 2 種のみ）。"""
    from jpdocread.read.structure.tree import Node, Tree, drop_paren_items

    t = Tree(doc_id="synthetic")
    t.add(Node(node_id="a", kind="article", label="第5条", citation="第5条"))
    t.add(Node(node_id="p", kind="paragraph", label="", citation="第5条", parent_id="a"))
    for nid, lab in (("i1", "①"), ("i2", "1．")):
        t.add(Node(node_id=nid, kind="item", label=lab, citation=f"第5条 {lab}", parent_id="p"))
    assert drop_paren_items(t) == 0
    assert sum(1 for n in t.nodes.values() if n.kind == "item") == 2

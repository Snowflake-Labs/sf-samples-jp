"""A2 — `item`（項の下の番号付き細分）。gold 実測 55 件。

`item` は実装が無いだけでなく**採点も無かった**ため、55 件が黙って 0 として
落ちていた。指標の欠落は「その種別が 1 つも出ない」という静かな失敗として現れる。
"""

from __future__ import annotations

from jpdocread.read.structure.tree import build_tree


class TestItemUnderParagraph:
    def test_dot_items_nest_under_circled_paragraph(self):
        """group 形：項は `②`（circled）、その下の細分が `1．`（dot）。

        **流儀が項と違うことが「1 段深い」ことの信号である。**
        """
        # **条は 2 つ以上必要。** 項の流儀は「その流儀が現れた条の数」の多数決で
        # 決まるので（A1）、条が 1 つしかないと `1．` と `②` が同数で決まらない。
        # 実文書の group は circled 27 対 dot 7 で分離する。
        #
        # **号の本文を「。」で終わらせない。** 号は文法上、項の文の一部を成す列挙な
        # ので文末を閉じない。gold の group-0001 は号 20 件のうち「。」終わりが 3 件
        # だけである。走査の 8 割以上が「。」で終わると `repair_items` が
        # 「文が並んだ表」と判定して降格する（W7・`tree.repair_items`）。
        pages = {
            1: "第1章総則\n"
            "第1条当会社は、次の各号のいずれかに該当するときは、保険金を支払いません。\n"
            "1．加入者の故意による場合\n"
            "2．保険金受取人の故意による場合\n"
            "②前項の規定にかかわらず、当会社は保険金を支払う場合があります。\n"
            "第2条当会社は、保険料の払込みを受けたときに責任を開始します。\n"
            "②前項の責任開始期は、保険証券に記載します。"
        }
        t = build_tree("g", pages)
        items = [n for n in t.nodes.values() if n.kind == "item"]
        paras = [n for n in t.nodes.values() if n.kind == "paragraph"]
        assert [i.label for i in items] == ["1．", "2．"]
        # 条ラベルの重複は無番号第一段落（A1）が担う。item 自身は 1 段深いだけ。
        assert items[0].citation == "第1章 第1条 第1条 1．"
        assert [p.label for p in paras] == ["第1条", "②", "第2条", "②"]

    def test_article_style_line_is_a_paragraph_not_an_item(self):
        """否定：条の下の流儀と一致する行は項である。item にしてはならない。"""
        pages = {
            1: "第1章総則\n"
            "第1条当会社は、保険金を支払います。\n"
            "②当会社は、前項の保険金を支払いません。"
        }
        t = build_tree("g2", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "item"] == []
        assert "②" in [n.label for n in t.nodes.values() if n.kind == "paragraph"]

    def test_region_lines_suppress_items_but_keep_the_text(self):
        """表の中の行は item にしない。**ただし本文としては必ず残す。**

        表領域の検出器は表と図を分離できないので本文の除去には使えない
        （条 recall 0.6302 → 0.5338 の退行）。`item` の抑止だけに使えば
        誤りの代償がその指標に限定される。
        """
        cell = "①記名被保険者。"
        pages = {1: "第1章総則\n第1条当会社は、被保険者の範囲を次のとおりとします。\n" + cell}
        t = build_tree("a", pages, region_lines={(1, cell)})
        assert [n for n in t.nodes.values() if n.kind == "item"] == []
        # **行は捨てない。** 本文はどこかのノードに残る（ラベルは段落側が取る）。
        # 段落の生成まで抑止する案も測ったが、正当な段落を失った
        # （段落 recall 0.5567 → 0.4936、適合率は 0.6646 → 0.6649 で横ばい）。
        # したがって抑止は `item` に限る。
        assert any("記名被保険者" in n.text for n in t.nodes.values())

    def test_item_is_not_created_without_an_open_article(self):
        """否定：条が開いていなければ item は作らない（別表の下の `1.` は段落）。"""
        pages = {1: "別表1保険金額表\n第1区分\n1．死亡保険金は、保険金額の全額とします。"}
        t = build_tree("x", pages)
        assert [n for n in t.nodes.values() if n.kind == "item"] == []

"""A7 — 上位見出しに散文を採らない（W7・T-C 第 1 案）。

**偽の上位見出しは 1 件で配下の全段落の引用を外す。** 実測では 8 件の偽見出しが
段落 FP 451 件のうち 43 件を汚染していた。段落 FP の 89.4% が「親の条が gold に
無い」に分類される — **段落適合率は条の経路の正しさに支配される。**
"""

from __future__ import annotations

from jpdocread.read.structure.tree import (
    RE_RIDER,
    _is_prose,
    _split_prose_head,
    build_tree,
)


class TestRiderNameIsNotASentence:
    def test_prose_ending_in_tokuyaku_is_not_a_rider(self):
        """`…場合を除き、特約` は本文の一部である（auto-0002 で実測）。

        `RE_RIDER` は「空白の無い 30 字以内で特約で終わる行」に一致するので、
        **正規表現だけでは分離できない。** 句読点の否定が要る。
        """
        s = "この表に定める意味は、特約において別に定める場合を除き、特約"
        assert RE_RIDER.match(s) is not None  # 正規表現は一致する
        pages = {1: "第1章総則\n" + s + "\n第1条当会社は、保険金を支払います。\n"}
        t = build_tree("r", pages)
        assert [n.kind for n in t.nodes.values() if n.kind == "rider"] == []

    def test_a_real_rider_name_still_opens(self):
        """否定対の肯定側：句読点の無い特約名は特約として開く。"""
        pages = {1: "ゴルフ用具新価特約\n第1条当会社は、保険金を支払います。\n"}
        t = build_tree("r2", pages)
        assert [n.label for n in t.nodes.values() if n.kind == "rider"] == ["ゴルフ用具新価特約"]


class TestProseDetection:
    def test_period_or_article_reference_is_prose(self):
        assert _is_prose("第4条(2)の算式は、相手方の財物を壊してしまったときの")
        assert _is_prose("第2章第4条にあります。")
        assert _is_prose("第3節第1条(2)の表のうちどの書類が必要かは、ご請求の内")

    def test_a_heading_with_a_comma_is_not_prose(self):
        """**「、を含む」を根拠にしてはならない。**

        teikan の `監査役、監査役会および会計監査人` は正当な章見出しである。
        読点は日本語の見出しに普通に現れる。
        """
        assert not _is_prose("監査役、監査役会および会計監査人")
        assert not _is_prose("総則")
        assert not _is_prose("")


class TestRunningHeadKeepsItsLabel:
    def test_chapter_label_is_kept_and_prose_goes_to_the_body(self):
        """**行ごと捨ててはならない。**

        高密度 2 段組では柱が継続ページで唯一の章情報源である。捨てると以後の条が
        `第2章` を失う（実測：auto-0001 b5-dense で条 TP 28 → 27、段落 56 → 52）。
        """
        assert _split_prose_head("第4条(2)の算式は、…") == ("", "第4条(2)の算式は、…")
        assert _split_prose_head("総則") == ("総則", "")

    def test_chapter_opens_with_empty_heading_and_article_is_cited_under_it(self):
        # 章を開いた直後は条番号の期待値が 1 になる（`expect_article`）。
        # 柱の散文が `第4条…` を指していても、**期待値は本文側の番号で決まる。**
        pages = {
            1: "第2章第4条(2)の算式は、相手方の財物を壊してしまったときの\n"
            "第1条当会社は、対物賠償保険金を支払います。\n"
        }
        t = build_tree("c", pages)
        ch = [n for n in t.nodes.values() if n.kind == "chapter"]
        assert [n.label for n in ch] == ["第2章"]
        assert ch[0].heading == ""
        arts = [n for n in t.nodes.values() if n.kind == "article"]
        assert arts[0].citation == "第2章 第1条"
        # 散文は失われず本文として残る。
        assert any("算式は" in "".join(n.lines) for n in t.nodes.values())


class TestChapterResetInference:
    """U-5 — 章が条番号をリセットするかの推定（`tree._infer_chapter_resets`）。

    **この推定は本コーパスの数値を 1 つも動かさなかった。** 当初の記録は
    「teikan の条 recall 0.694 の一因」と書いていたが、**その帰属は誤りだった**：
    teikan の条見出しは `第6条（取締役会）` のように見出し括弧を持つので、
    期待値が合わなくても「不連続かつ見出し無し」の否定規則に掛からず、
    再同期して受理されていた。teikan の真因は別で（W7 §3 に帰属）、

      (a) 大域デコードが p2 の `第１条（商号）`〜`第３条` を非採用にしている
      (b) 章が 1 つ余計に開き、以降の章ラベルが 1 つずれる

    である。**推定そのものは正しく動く**ので、体裁差の記述として残す。
    数値が動かないことを承知の上で残している、という事実をここに固定する。
    """

    def _seq(self, text):
        return [(1, ln) for ln in text.split("\n")]

    def test_continuous_numbering_is_detected(self):
        """teikan 形：第1章 条1〜2 ／ 第2章 条3〜4（章をまたいで連番）。"""
        from jpdocread.read.structure.tree import _infer_chapter_resets

        seq = self._seq(
            "第1章総則\n第1条（商号）\n第2条（目的）\n第2章株式\n第3条（発行可能株式総数）\n第4条（株券）"
        )
        assert _infer_chapter_resets(seq, set()) is False

    def test_per_chapter_reset_is_detected(self):
        """golf / auto 形：章ごとに条番号が 1 に戻る。"""
        from jpdocread.read.structure.tree import _infer_chapter_resets

        seq = self._seq(
            "第1章総則\n第1条（用語）\n第2条（範囲）\n第2章補償\n第1条（保険金）\n第2条（免責）"
        )
        assert _infer_chapter_resets(seq, set()) is True

    def test_no_evidence_defaults_to_reset(self):
        from jpdocread.read.structure.tree import _infer_chapter_resets

        assert _infer_chapter_resets(self._seq("第1章総則\n第1条（用語）"), set()) is True
        assert _infer_chapter_resets([], set()) is True

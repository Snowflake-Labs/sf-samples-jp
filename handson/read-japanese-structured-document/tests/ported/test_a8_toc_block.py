"""A8 — 目次抑止の単位は「ページ」ではなく「目次ブロック」（W8）。

**目次と本文が同居するページがある。** teikan の p2 は

    [柱] 第１章総則 / もくじ / 第１章総則2 …（目次 9 行）
    / 第１章総則（本文の章見出し）/ 第１条（商号）/ 本文…

という構造で、ページ全体を抑止すると **gold の `第1章 第1〜5条` が丸ごと落ちる**。

実測（ALL 39 文書・`greedy`）：条 recall 0.8220 → **0.8478**、
段落パス完全一致 0.7457 → **0.7744**、`item` recall 0.4294 → **0.5000**。
**組み立て側とデコーダ側の両方を同じ関数で直す必要があった** — 組み立て側だけ直した
第 1 版では第1条〜第3条が「大域デコードが非採用」で落ち続け、条 recall は +0.0009 しか
動かなかった（0.8220 → 0.8229）。
"""

from __future__ import annotations

from jpdocread.read.structure.lines import RE_TOC_ENTRY, toc_block_end

_TEIKAN_P2 = "\n".join(
    [
        "第１章総則",  # 0 柱
        "もくじ",  # 1
        "第１章総則2",  # 2 目次
        "第２章社員3",  # 3 目次
        "第８章解散および清算10",  # 4 目次
        "附則11",  # 5 目次（**W13 T45 で語彙に `附則` を足して一致するようにした**）
        "第１章総則",  # 6 本文の章見出し
        "第１条（商号）",  # 7 本文
        "当会社は、常盤あかね生命保険相互会社と称する。",  # 8
    ]
)


class TestBlockBoundary:
    def test_cut_is_the_last_recognised_toc_line(self):
        """**★ 期待値を 4 → 5 に改めた（W13 T45）。**

        W8 版はこの行に `assert cut == {2: 4}` と書き、fixture の注釈にも
        「`附則11` は目次だが `RE_TOC_ENTRY` に一致しない」と書いていた。
        **欠陥をそのまま期待値として固定していた**（`附則` が語彙から漏れていた）。

        その漏れの代償は `appendix_section` 再現率 0.8312 で、
        **欠落 13 件のうち 9 件**が「p2 で `附則` が開いて本文 p11 が `_dup` に吸収される」
        という形だった（W12 T38 機構 1）。語彙に `附則` を足して 0.9740 になった。

        **この 1 件は「現実の反例」ではなく「古い契約」である**（規律 2）。
        判定の根拠は、テストの本来の目的（本文見出しがブロックの外に来ること）が
        `cut = 5` でも保たれていること — 下の `test_body_headings_fall_outside_the_block`
        が無改変で通る。
        """
        cut = toc_block_end({2: _TEIKAN_P2}, {2})
        assert cut == {2: 5}

    def test_body_headings_fall_outside_the_block(self):
        """**本文の章見出しと条見出しがブロックの外に来ることが要点である。**"""
        cut = toc_block_end({2: _TEIKAN_P2}, {2})[2]
        lines = _TEIKAN_P2.split("\n")
        assert lines[6] == "第１章総則" and cut < 6
        assert lines[7] == "第１条（商号）" and cut < 7

    def test_page_with_no_toc_line_is_suppressed_whole(self):
        """裸の見出し列ページ（auto の p3–4）は従来どおり全体を抑止する。

        番号もページ番号も持たない見出しだけが並ぶので目次行に一致しない。
        ここで `-1` を返すと構成ページの見出しが全部偽陽性になる（T7 の実測）。
        """
        page = "普通保険約款\n賠償責任条項\n人身傷害条項"
        cut = toc_block_end({3: page}, {3})
        assert cut[3] >= len(page.split("\n")) - 1

    def test_pages_not_in_toc_set_are_absent(self):
        assert toc_block_end({1: "第１章総則", 2: "第１章総則2"}, {2}) == {2: 0}


class TestTocLineRecognition:
    def test_toc_entry_needs_a_trailing_page_number(self):
        """目次行の定義的性質は**末尾の裸のページ番号**である。"""
        assert RE_TOC_ENTRY.match("第１章総則2")
        assert RE_TOC_ENTRY.match("第８章解散および清算10")
        # 否定対：本文の見出しは裸の数字で終わらない
        assert not RE_TOC_ENTRY.match("第１章総則")
        assert not RE_TOC_ENTRY.match("第１条（商号）")

    def test_a_body_sentence_starting_with_a_heading_token_is_not_a_toc_line(self):
        """否定対：本文中の参照。"""
        s = "第２章第３条の定めによって決まります。"
        assert not (RE_TOC_ENTRY.match(s) and "。" not in s)


class TestFurnitureUpperHeadings:
    """柱（running head）の上位見出しを開かない（W8 第 2 案）。

    **これが W8 で最も効いた変更である。** teikan の p3 は

        0: 第２章社員（柱） / 1: 第４条（公告方法） / … / 25: 第２章社員（本物）

    という並びで、先着を章の開始と採ると gold の `第1章 第4/5条` が `第2章` 配下に落ちる。
    実測（ALL 39 文書）：条 recall 0.8478 → **0.9080**、条適合率 0.8931 → **0.9312**、
    段落パス完全一致 0.7744 → **0.8472**、段落適合率 0.8619 → **0.9299**。
    条 recall 1.000 の文書は 6 → **20**。
    """

    def test_no_geometry_means_no_suppression(self):
        """**幾何が無い経路では何も落とさない。**

        位置だけで「先着が柱」と決める実装を試して棄却した。フッタに柱を刷る版面では
        本物が先に来るので、本物を落としてしまう
        （`test_s4_structure.py::test_repeated_rider_name_does_not_duplicate` が失敗した）。
        """
        from jpdocread.read.structure.tree import _furniture_upper_lines

        pages = {1: "弁護士費用特約\n第1条（適用条件）\n弁護士費用特約\n本文。"}
        assert _furniture_upper_lines(None, pages) == set()
        assert _furniture_upper_lines("", pages) == set()

    def test_real_document_running_heads_are_found(self):
        """実文書で柱が特定できることを固定する（teikan p3 の `第２章社員`）。"""
        from jpdocread.read.parse.r4_local import read_pages_text
        from jpdocread.read.structure.lines import split_page_text
        from jpdocread.read.structure.tree import _furniture_upper_lines

        doc = "teikan-0001--teikan-a4-1col-mincho"
        pages = {pt.page: split_page_text(pt.text) for pt in read_pages_text(doc)}
        f = _furniture_upper_lines(doc, pages)
        assert (3, 0) in f, "p3 先頭の柱 `第２章社員` を柱と判定していない"
        rows = pages[3].split("\n")
        assert rows[0].strip() == "第２章社員"
        # 本物（後ろ側）は落とさない。
        assert (3, 25) not in f
        assert rows[25].strip() == "第２章社員"

    def test_the_chapter_boundary_is_correct_in_the_real_document(self):
        """gold と突き合わせた最終形：teikan-0001 の条 recall は 1.000 になる。"""
        # 親は eval.e7_structure.score_doc で採点していた。本リポジトリでは同じ規則を
        # eval.evaluate.structure_scores が出力 JSON の outline に対して行う（木から outline を作って渡す）
        from jpdocread.eval.evaluate import structure_scores
        from jpdocread.read.integrate import _outline
        from jpdocread.read.structure.tree import build_tree_for_doc

        doc = "teikan-0001--teikan-a4-1col-mincho"
        r = structure_scores(doc, {"outline": _outline(build_tree_for_doc(doc))})
        assert r["article"]["recall"] == 1.0

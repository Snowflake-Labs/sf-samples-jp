"""W14 — 柱除去が本物の章見出しを消していた欠陥（T50 第 1 案）。

**同一ページに「柱」と「本物の見出し」が並ぶ体裁がある。** 章見出しは章の初出ページの
本文と後続ページの柱の両方に現れるので、柱の反復キーは必ず `min_repeat` を満たし、
**初出ページでは両方が余白帯に入って両方落とされていた。**

| 文書 | ページ | `text` 中 | `text_with_furniture` 中 |
|---|---|---:|---:|
| `auto-0001-b5`（`第2章賠償責任条項`） | p6 | 0 → **1** | 2 |
| `quake-0002`（`第2章保険金を支払う場合`） | p4 | 0 → **1** | 2 |

W13 はこれを「読み取り層の損失。D-8 待ち」と誤って帰属した。**課金 0 で直る欠陥だった。**
"""

from __future__ import annotations

import unicodedata

from jpdocread.read.geometry import read_lines
from jpdocread.read.parse.r4_local import _norm_key, detect_furniture, read_pages, read_pages_text


def _flat(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace("\u3000", "").replace(" ", "").strip()


class TestGenuineHeadingSurvivesFurnitureRemoval:
    """否定例は柱そのもの、肯定例は同一ページに写り込んだ本物の見出しである。"""

    def test_chapter_heading_is_kept_on_its_first_page(self):
        """`auto-0001-b5` p6 の実物。**これが欠けると配下の全段落が親を失う。**"""
        pages = {pt.page: pt for pt in read_pages_text("auto-0001--nl-b5-2col-dense")}
        got = [x for x in pages[6].text.split("\n") if _flat(x).startswith("第2章賠償責任条項")]
        assert len(got) == 1, "柱と本物の 2 行のうち 1 行（本物）だけが残ること"

    def test_same_defect_in_another_document(self):
        """`quake-0002` p4。**版面（`b5-2col-dense`）に依存する体裁である。**"""
        pages = {pt.page: pt for pt in read_pages_text("quake-0002--nl-b5-2col-dense")}
        got = [
            x for x in pages[4].text.split("\n") if _flat(x).startswith("第2章保険金を支払う場合")
        ]
        assert len(got) == 1

    def test_running_head_on_later_pages_is_still_removed(self):
        """肯定対：**2 ページ目以降の柱は落ち続ける**（1 回しか現れないので免除されない）。"""
        pages = {pt.page: pt for pt in read_pages_text("auto-0001--nl-b5-2col-dense")}
        for pg in (7, 8):
            got = [
                x for x in pages[pg].text.split("\n") if _flat(x).startswith("第2章賠償責任条項")
            ]
            assert got == [], f"p{pg} の柱は落ちること"

    def test_page_numbers_are_still_removed_even_when_duplicated(self):
        """肯定対：**ページ番号は同一ページで重複しても両方落とす。**

        非 gold の 7 グループはすべてページ番号だった（`10`・`11`・`8`・`12`）。
        `_PAGENO_RE` の分岐を免除から外してあることを確かめる
        — 外し忘れるとページ番号が本文に漏れて漏出率が上がる。

        **判定は余白帯の中だけを見る。** `detect_furniture` は帯の外を候補にしないので、
        表の中の `5` のような数字行を混ぜると、コードではなくテストが誤る
        （最初の版はそれで落ちた）。
        """
        doc = "auto-0001--nl-b5-2col-dense"
        lines = read_lines(doc)
        furn = detect_furniture(doc, lines)
        pages = {p.page: p for p in read_pages(doc)}
        band = 0.07
        in_band = [
            ln
            for ln in lines
            if ln.text.strip().isdigit()
            and (
                ln.y0 <= pages[ln.page].height * band
                or ln.y1 >= pages[ln.page].height * (1.0 - band)
            )
        ]
        assert in_band, "前提：余白帯にページ番号だけの行が存在する"
        kept = [ln for ln in in_band if (ln.page, ln.line_no) not in furn]
        assert kept == [], "余白帯のページ番号は 1 行も本文に残さないこと"

    def test_detector_keeps_exactly_one_per_duplicated_group(self):
        """退化ケースの対照：重複グループの**上側 1 行だけ**が柱として残ること。"""
        doc = "quake-0002--nl-b5-2col-dense"
        lines = read_lines(doc)
        furn = detect_furniture(doc, lines)
        grp = [
            ln
            for ln in lines
            if ln.page == 4 and _norm_key(ln.text) == _norm_key("第2章保険金を支払う場合")
        ]
        assert len(grp) == 2, "前提：p4 に 2 行ある"
        marked = [ln for ln in grp if (ln.page, ln.line_no) in furn]
        assert len(marked) == 1
        assert marked[0].y0 == min(ln.y0 for ln in grp), "上にある側（柱）を落とすこと"

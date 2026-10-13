"""構造組み立ての対象外にするページの判定（幾何のみ）。

**★訂正（2026-09-25・D-16）。** 元は「E2 の実測（P20 20 ページ）：目次 P=R=1.000、
表紙 P=R=1.000」と書いていた。**目次判定の 1.000 は ALL 39 文書では成り立たない。**

ALL 39 の実測（W10）：

    目次（狭い判定＝点線リーダー）      R 0.9091 / P 1.0000 / F1 0.9524
    目次（本番経路＝点線リーダー ∪ 裸の見出し列）  R 0.7727 / P 0.9444 / F1 0.8500
    表紙                            P = R = 1.0000（39/39）← 再現した

20 ページで測った値を 527 ページの主張として流用していた
（記録に無い結果を主張しない、という規律が守っていたのはこれである）。
**表紙の 1.000 は再現したが、目次の 1.000 は再現しなかった。**

図の判定は使えない（P=0.200）ので、ここでは目次と表紙だけを外す。
"""

from __future__ import annotations

from ..geometry import read_lines, read_pages

DOTTED_LEADER_MIN = 800  # 点線リーダーの線分オブジェクト数
COVER_MAX_CHARS = 400


def toc_pages(doc_id: str) -> set[int]:
    """目次ページ（点線リーダーの線分オブジェクト数で判定）。

    **ALL 39 の実測は R 0.9091 / P 1.0000**（W10・D-16 で訂正）。
    適合率は 1.000 だが**再現率は 1.000 ではない** — 点線リーダーを持たない
    目次（裸の見出し列）を取り落とす。本番経路はそれを `outline_pages` で補うが、
    補った後の合成集合は R 0.7727 / P 0.9444 に下がる。

    **ページごと落とすのではなく、上位見出しだけを抑止する**のに使う
    （目次と本文は同一ページに同居する）。
    """
    return {p.page for p in read_pages(doc_id) if p.n_line_objs > DOTTED_LEADER_MIN}


def cover_pages(doc_id: str) -> set[int]:
    """表紙のみ。**目次はページ単位で外してはならない**（本文と同居する）。"""
    lines = read_lines(doc_id)
    chars: dict[int, int] = {}
    for ln in lines:
        chars[ln.page] = chars.get(ln.page, 0) + len(ln.text)
    return {1} if chars.get(1, 0) < COVER_MAX_CHARS else set()


def non_body_pages(doc_id: str) -> set[int]:
    lines = read_lines(doc_id)
    chars: dict[int, int] = {}
    for ln in lines:
        chars[ln.page] = chars.get(ln.page, 0) + len(ln.text)
    out: set[int] = set()
    for p in read_pages(doc_id):
        if p.n_line_objs > DOTTED_LEADER_MIN:
            out.add(p.page)
        if p.page == 1 and chars.get(p.page, 0) < COVER_MAX_CHARS:
            out.add(p.page)
    return out

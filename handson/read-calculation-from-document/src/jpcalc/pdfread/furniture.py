"""柱（走りヘッダ・フッタ・ページ番号）の決定的な判定。

handson/read-japanese-structured-document の read/parse/r4_local.py の detect_furniture を切り出した。
変更点は入力だけで、判定は同じ：ページの幾何を引数で受け取る（文書 ID から読み直さない）。
**予測側のモジュールである。** 正解を開かない。
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from .geometry import Line, PageGeom

# ページ番号らしい行（柱の一部として除去する）
_PAGENO_RE = re.compile(r"^[\s\-—―（(]*[0-9０-９]{1,4}[\s\-—―）)]*$")


def _norm_key(s: str) -> str:
    """柱の反復判定用のキー。数字を伏せて比較する（ページ番号付き柱を同一視するため）。"""
    s = "".join(s.split())
    return re.sub(r"[0-9０-９]+", "#", s)


def detect_furniture(
    page_geoms: Iterable[PageGeom],
    lines: list[Line],
    band: float = 0.07,
    min_repeat: int = 3,
) -> set[tuple[int, int]]:
    """柱（走りヘッダ/フッタ・ページ番号）の (page, line_no) 集合を返す。

    判定は 2 条件の AND ではなく OR で、**余白帯にあること**を前提に
    (a) 正規化キーが `min_repeat` ページ以上で反復する、または
    (b) ページ番号パターンに一致する。

    柱は捨てるが、呼び出し側でページ属性として保持できるよう内容も返せるようにしている
    （柱は検証の手掛かりになる）。
    """
    pages = {p.page: p for p in page_geoms}
    cand: list[Line] = []
    for ln in lines:
        pg = pages.get(ln.page)
        if pg is None:
            continue
        top_band = pg.height * band
        bot_band = pg.height * (1.0 - band)
        if ln.y0 <= top_band or ln.y1 >= bot_band:
            cand.append(ln)

    # 正規化キーごとに、出現したページ数を数える
    key_pages: dict[str, set[int]] = defaultdict(set)
    for ln in cand:
        key_pages[_norm_key(ln.text)].add(ln.page)

    furniture: set[tuple[int, int]] = set()
    for ln in cand:
        k = _norm_key(ln.text)
        if len(key_pages[k]) >= min_repeat or _PAGENO_RE.match(ln.text.strip()):
            furniture.add((ln.page, ln.line_no))

    # **同一ページに同じキーが 2 行以上あるときは、最上行だけを柱にする。**
    #
    # 章見出しは「章の初出ページの本文」と「後続ページの柱」の両方に現れるので、
    # キーは当然 `min_repeat` ページ以上で反復する。その結果**初出ページでは
    # 柱と本物が同一ページに並び、従来は両方を落としていた。**
    # 落ちた見出しの配下は全部親を失うので、代償は 1 行ぶんではない。
    #
    # **数えてから入れた。** 39 文書で「同一ページに同じ柱キーが 2 行以上」は 11 グループあり、
    # 完全に 2 つに分かれた：
    #
    #   構造見出し 4 件  … (y0/h=0.022, 行 0) ＋ (y0/h=0.062, 行 1 など)。章見出し（第2章・第4章）
    #   それ以外 7 件    … **すべてページ番号**。(0.92, 0.96) か (0.057, 0.965)
    #
    # よって「ページ番号でないキーが同一ページで反復したら、最上行以外は本文」で
    # 4 件を回復し、それ以外を 1 件も拾わない。ページ番号は `_PAGENO_RE` が
    # ページ単位の重複と無関係に拾い続ける（下の `continue`）。
    #
    # **上端・下端のどちらに寄っているかでは決められない。** ページ番号の 7 件には
    # 上端と下端に分かれた対（0.057 と 0.965）があり、帯の側では分離しない。
    # 分離するのは「ページ内で最も上か」である。
    by_page_key: dict[tuple[int, str], list[Line]] = defaultdict(list)
    for ln in cand:
        if (ln.page, ln.line_no) in furniture:
            by_page_key[(ln.page, _norm_key(ln.text))].append(ln)
    for (_pg, _k), group in by_page_key.items():
        if len(group) < 2 or _PAGENO_RE.match(group[0].text.strip()):
            continue
        for ln in sorted(group, key=lambda x: x.y0)[1:]:
            furniture.discard((ln.page, ln.line_no))
    return furniture

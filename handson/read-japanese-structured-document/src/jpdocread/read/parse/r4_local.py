"""R4 — ローカル決定的リーダー（AI なしの対照）。

born-digital の本コーパスで「AI が何を足しているか」を測るための基準線。
S2 以降ずっと対照として効く。**gold を開かない。**

出力は `PAGE_TEXT` 相当：ページごとの `text`（柱除去済）と `text_with_furniture`。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ..geometry import Line, read_lines, read_pages

# ページ番号らしい行（柱の一部として除去する）
_PAGENO_RE = re.compile(r"^[\s\-—―（(]*[0-9０-９]{1,4}[\s\-—―）)]*$")


@dataclass
class PageText:
    doc_id: str
    page: int
    text: str
    text_with_furniture: str
    n_lines: int
    n_furniture_lines: int
    n_figure_label_lines: int
    furniture: list[str]


def _norm_key(s: str) -> str:
    """柱の反復判定用のキー。数字を伏せて比較する（ページ番号付き柱を同一視するため）。"""
    s = "".join(s.split())
    return re.sub(r"[0-9０-９]+", "#", s)


def detect_furniture(
    doc_id: str,
    lines: list[Line],
    band: float = 0.07,
    min_repeat: int = 3,
) -> set[tuple[int, int]]:
    """柱（走りヘッダ/フッタ・ページ番号）の (page, line_no) 集合を返す。

    判定は 2 条件の AND ではなく OR で、**余白帯にあること**を前提に
    (a) 正規化キーが `min_repeat` ページ以上で反復する、または
    (b) ページ番号パターンに一致する。

    柱は捨てるが、呼び出し側でページ属性として保持できるよう内容も返せるようにしている
    （柱は P6 の検証信号になる）。
    """
    pages = {p.page: p for p in read_pages(doc_id)}
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

    # **同一ページに同じキーが 2 行以上あるときは、最上行だけを柱にする（W14 T50）。**
    #
    # 章見出しは「章の初出ページの本文」と「後続ページの柱」の両方に現れるので、
    # キーは当然 `min_repeat` ページ以上で反復する。その結果**初出ページでは
    # 柱と本物が同一ページに並び、従来は両方を落としていた。**
    # 落ちた見出しの配下は全部親を失うので、代償は 1 行ぶんではない。
    #
    # **数えてから入れた**（規律 8）。ALL 39 で「同一ページに同じ柱キーが 2 行以上」は
    # 11 グループあり、**完全に 2 つに分かれる**：
    #
    #   gold の構造見出し 4 件 … (y0/h=0.022, 行 0) ＋ (y0/h=0.062, 行 1 など)
    #                            auto-0001-b5 p6 第2章／quake-0002 p4 第2章／
    #                            health-0001-b5 p9 第4章／health-0002 p9 第4章
    #   非 gold 7 件      … **すべてページ番号**。(0.92, 0.96) か (0.057, 0.965)
    #
    # よって「ページ番号でないキーが同一ページで反復したら、最上行以外は本文」で
    # 4 件を回復し、非 gold を 1 件も拾わない。ページ番号は `_PAGENO_RE` が
    # ページ単位の重複と無関係に拾い続ける（下の `continue`）。
    #
    # **上端・下端のどちらに寄っているかでは決められない。** 非 gold の 7 件には
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


def detect_repeated_table_headers(lines: list[Line], min_repeat: int = 3) -> set[tuple[int, int]]:
    """繰り返し表頭の再掲を検出する（gold では `repeated: true`）。

    余白帯ではなく本文中に現れるため、柱とは別に扱う。同一文字列が 3 ページ以上に
    現れ、かつ短い（表頭らしい）ものを候補にする。
    """
    key_pages: dict[str, set[int]] = defaultdict(set)
    for ln in lines:
        t = "".join(ln.text.split())
        if 0 < len(t) <= 30:
            key_pages[t].add(ln.page)
    repeated_keys = {k for k, ps in key_pages.items() if len(ps) >= min_repeat}
    out: set[tuple[int, int]] = set()
    if not repeated_keys:
        return out
    seen: Counter[str] = Counter()
    for ln in lines:
        t = "".join(ln.text.split())
        if t in repeated_keys:
            seen[t] += 1
            if seen[t] > 1:  # 初出は残し、2 回目以降を再掲として落とす
                out.add((ln.page, ln.line_no))
    return out


def detect_figure_label_lines(doc_id: str, lines: list[Line]) -> set[tuple[int, int]]:
    """図の内部ラベル行を返す。

    **採点契約の実測（S0 で確定）：** gold の `pages[].text` は本文・表セル・脚注・
    キャプション・見出しを 100% 含むが、**図の内部ラベル（`figure_node`）は含まない**
    （auto-0001 で 64 件中一致 15.6%、その一致は短いラベルの偶然一致）。
    したがって本文テキストからは図内ラベルを除く必要がある。

    判定は P2 の図領域（`PageGeom.figure_boxes`）に**行の中心が入るか**。
    キャプション（`図1　…`）は図領域の外にあるので残る。

    **ただし既定では無効（`drop_figure_labels=False`）。** S0 の実測で、描画
    プリミティブ（rect / line / curve）からは **表領域と図領域を十分に分離できない**
    ことが判明した。線で描かれた表を図と誤認し、表セル本文を削除して CER が
    0.206 → 0.305 に悪化した（auto-0001 p5 が 0.026 → 0.906）。
    壊れた検出器で黙って本文を消すより、既知バイアスとして残すほうが誠実である
    。図と表の分離は S3（E4）で VLM を使って解く。
    """
    pages = {p.page: p for p in read_pages(doc_id)}
    out: set[tuple[int, int]] = set()
    for ln in lines:
        pg = pages.get(ln.page)
        if pg is None or not pg.figure_boxes:
            continue
        cx = (ln.x0 + ln.x1) / 2.0
        cy = (ln.y0 + ln.y1) / 2.0
        for b in pg.figure_boxes:
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                out.add((ln.page, ln.line_no))
                break
    return out


def detect_region_lines(doc_id: str, lines: list[Line]) -> set[tuple[int, int]]:
    """**表領域・図領域の内側にある行**の (page, line_no) を返す。

    構造パス（P5）専用である。**本文パス（CER）では使ってはならない。**
    gold の `pages[].text` は表セルを 100% 含むので、本文から落とすと CER が
    悪化する（S0 実測 0.206 → 0.305）。一方 gold の**構造ノードは表セルを含まない**：

    - auto の `①記名被保険者。`〜 は gold では `kind='cell'` / `figure_node` で
      `node_kind` を持たない（＝引用木のノードではない）
    - teikan の `（１）生命保険業` も `kind='cell'`

    これを本文行として P5 に食わせると、**表のセルが項や号として木に生える**
    （実測：auto で偽の `item` 48 件、teikan で 15 件）。
    したがって落とす層は「本文か構造か」で分かれる。同じ検出器を両方に使うと
    どちらかが必ず悪化する。

    判定は行の中心が領域に入るか。キャプション（`図1　…`・`別表1`）は
    領域の外にあるので残る — これは意図通りで、`別表` は構造ノードである。
    """
    pages = {p.page: p for p in read_pages(doc_id)}
    out: set[tuple[int, int]] = set()
    for ln in lines:
        pg = pages.get(ln.page)
        if pg is None:
            continue
        cx = (ln.x0 + ln.x1) / 2.0
        cy = (ln.y0 + ln.y1) / 2.0
        for b in list(pg.table_boxes) + list(pg.figure_boxes):
            if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                out.add((ln.page, ln.line_no))
                break
    return out


def _join_cjk_lines(texts: list[str]) -> str:
    """行を連結する。**CJK 間に空白を入れない**。

    ここでは行を改行で保持する。ページ本文の比較は空白除去後に行うため（§10.1）、
    改行の有無は CER に影響しない。
    """
    return "\n".join(texts)


def read_pages_text(
    doc_id: str,
    # **S2 E5 の実測で既定 off に変更。** 柱を除去すると CER が悪化する
    # （0.0410 → 0.0428）。検出 41 行のうち 3 行は gold 本文に含まれていた。
    # gold のページ本文は柱を排除していないので、本文パスで落としてはならない。
    # 柱の扱いは構造パス（P5）の責務。
    drop_repeated_headers: bool = False,
    drop_figure_labels: bool = False,  # S0 の実測で既定 off（下記）
    # **構造パス（P5）専用。** 表・図領域の内側の行を落とす。既定 off。
    # 本文パスで on にすると CER が悪化する（`detect_region_lines` の docstring）。
    drop_region_lines: bool = False,
) -> list[PageText]:
    lines = read_lines(doc_id)
    furn = detect_furniture(doc_id, lines)
    rep = detect_repeated_table_headers(lines) if drop_repeated_headers else set()
    figlab = detect_figure_label_lines(doc_id, lines) if drop_figure_labels else set()
    if drop_region_lines:
        figlab = figlab | detect_region_lines(doc_id, lines)

    by_page: dict[int, list[Line]] = defaultdict(list)
    for ln in lines:
        by_page[ln.page].append(ln)

    out: list[PageText] = []
    for page in sorted(by_page):
        pls = by_page[page]  # read_lines は読み順を保っている
        all_texts = [ln.text for ln in pls]
        keep, furn_texts = [], []
        for ln in pls:
            key = (ln.page, ln.line_no)
            if key in furn:
                furn_texts.append(ln.text)
            elif key in rep or key in figlab:
                continue  # 表頭の再掲 / 図内ラベル。柱ではないので furniture に数えない
            else:
                keep.append(ln.text)
        out.append(
            PageText(
                doc_id=doc_id,
                page=page,
                text=_join_cjk_lines(keep),
                text_with_furniture=_join_cjk_lines(all_texts),
                n_lines=len(pls),
                n_furniture_lines=len(furn_texts),
                n_figure_label_lines=sum(1 for ln in pls if (ln.page, ln.line_no) in figlab),
                furniture=furn_texts,
            )
        )
    return out

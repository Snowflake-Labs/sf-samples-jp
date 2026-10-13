"""P2 — ローカル幾何。

`AI_PARSE_DOCUMENT` が bbox / フォント / 信頼度を一切返さない（§3.1）ため、
born-digital の本コーパスでは幾何をローカルで取得する。ここが段の割当・柱検出・
文字単位インデントの基盤になる。

**予測側のモジュールである。** gold を開いてはならない。
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

from ..common.paths import WORK, doc_pdf


@dataclass
class Line:
    doc_id: str
    page: int  # 1-based
    line_no: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    font: str | None
    size: float | None
    char_w: float | None  # このラインの平均文字幅

    @property
    def width(self) -> float:
        return self.x1 - self.x0


@dataclass
class PageGeom:
    doc_id: str
    page: int
    width: float
    height: float
    n_lines: int
    n_rects: int
    n_curves: int
    n_line_objs: int
    # 罫線の矩形群から推定した表領域、そうでない矩形/線の塊から推定した図領域
    table_boxes: list[list[float]]
    # table_boxes と同じ順序・同じ長さ。各表領域のセル数（`max_tokens` 算出用）
    table_cells: list[int]
    figure_boxes: list[list[float]]
    column_bands: list[list[float]]
    mean_char_w: float | None
    gutter: float | None
    n_cols: int


def free_profile(words: list[dict], page_w: float, page_h: float) -> tuple[list[float], int]:
    """x ごとの「その x が空いている本文行の割合」と、使われた行数を返す。"""
    ymin, ymax = page_h * 0.07, page_h * 0.93
    body = [w for w in words if ymin <= w["top"] <= ymax]
    xstep, ystep = 1.0, 4.0
    nx = int(page_w / xstep) + 1
    ny = int(page_h / ystep) + 1
    if len(body) < 20:
        return [0.0] * nx, 0
    occ = [bytearray(nx) for _ in range(ny)]
    rows_used: set[int] = set()
    for w in body:
        ya = max(0, int(w["top"] / ystep))
        yb = min(ny - 1, int(w["bottom"] / ystep))
        xa = max(0, int(w["x0"] / xstep))
        xb = min(nx - 1, int(w["x1"] / xstep))
        for y in range(ya, yb + 1):
            rows_used.add(y)
            row = occ[y]
            for x in range(xa, xb + 1):
                row[x] = 1
    used = sorted(rows_used)
    n_used = len(used) or 1
    free = [0.0] * nx
    for x in range(nx):
        c = 0
        for y in used:
            if not occ[y][x]:
                c += 1
        free[x] = c / n_used
    return free, len(used)


def _widest_band(
    free: list[float], thr: float, lo_frac=0.30, hi_frac=0.70
) -> tuple[int, int] | None:
    nx = len(free)
    lo, hi = int(nx * lo_frac), int(nx * hi_frac)
    best: tuple[int, int] | None = None
    i = lo
    while i <= hi:
        if free[i] >= thr:
            j = i
            while j <= hi and free[j] >= thr:
                j += 1
            if best is None or (j - i) > (best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    return best


def find_gutter(words: list[dict], page_w: float, page_h: float, thr: float = 0.97) -> float | None:
    """このページ単独での gutter 候補。

    **真の gutter は本文高さのほぼ全体に渡る縦の白帯である。** 表の内部にも局所的な
    空隙はあるので、1 次元の被覆だけで判定すると gutter が表を貫通してセルを分断する
    （実測：`通知義`+`務`、`第10`+`級` に割れた）。そこで 2 次元占有を使い、
    **「その x が空いている行の割合」が閾値以上の x 帯**だけを gutter と認める。
    """
    free, n_used = free_profile(words, page_w, page_h)
    if n_used == 0:
        return None
    band = _widest_band(free, thr)
    if band is None or (band[1] - band[0]) < 8.0:
        return None
    return (band[0] + band[1]) / 2.0


def document_gutter(page_words: list[tuple[list[dict], float, float]]) -> float | None:
    """**文書全体の gutter を決める。**

    段組は個々のページの性質ではなく **文書スタイルの属性** である
    （`nl-a4-2col-mincho` なら全ページ 2 段）。ページ単位で判定すると、
    図だけのページで偽の縦白帯を拾い（実測 p4）、表が上部を占めるページでは
    検出漏れになる（実測 p16）。そこで候補の最頻値を文書の gutter とする。
    """
    cands: list[float] = []
    for words, w, h in page_words:
        g = find_gutter(words, w, h, thr=0.97)
        if g is None:
            g = find_gutter(words, w, h, thr=0.90)
        if g is not None:
            cands.append(g)
    if len(cands) < 2:
        return None
    # 2pt 丸めの最頻値。同数なら中央値に近いものを採る
    buckets = Counter(round(c / 2.0) * 2.0 for c in cands)
    top = max(buckets.values())
    modal = sorted(c for c, n in buckets.items() if n == top)
    med = statistics.median(cands)
    return min(modal, key=lambda c: abs(c - med))


def _cluster_words_to_lines(words: list[dict], y_tol: float = 2.5) -> list[list[dict]]:
    """pdfplumber の word を y でクラスタして行にする（同一段内で呼ぶこと）。"""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lines: list[list[dict]] = []
    cur: list[dict] = [ws[0]]
    for w in ws[1:]:
        if abs(w["top"] - cur[-1]["top"]) <= y_tol:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x["x0"]))
            cur = [w]
    lines.append(sorted(cur, key=lambda x: x["x0"]))
    return lines


def lines_in_reading_order(
    words: list[dict],
    page_w: float,
    page_h: float,
    y_tol: float = 2.5,
    gutter: float | None = None,
    span_ratio_max: float = 0.40,
    snap_gutter: bool = False,
) -> tuple[list[list[dict]], float | None, int]:
    """段を考慮した読み順で行を返す。

    手順：
    1. gutter を検出
    2. 語を left / right / spanning（段を跨ぐ全幅要素）に分類
    3. 各群を y でクラスタして行にする
    4. **spanning 行がページを縦に区切る**。各ゾーン内で 左段 → 右段 の順に出す

    `gutter` は **文書全体で決めた値**を渡す（document_gutter）。跨ぐ語が
    `span_ratio_max` を超えるページは全幅ページと見なして 1 段で読む。

    戻り値: (行のリスト, 適用した gutter, 段数)
    """
    if gutter is None:
        return _cluster_words_to_lines(words, y_tol), None, 1

    if snap_gutter:
        # **契約書だけ（C-012・T11.4）。** 文書の gutter は白帯の中央とは限らず、左段の行末より左に出ることがある
        # （pur-0004 A3：gutter 566pt、左段の行末 578pt、右段の行頭 609pt）。そのままだと左段いっぱいの行が
        # 「段を跨ぐ行」になり、そこでゾーンが切れて右段の先頭行が前文より前に出る。
        # そこで分割点を、このページで gutter より右にある語の最小 x0（右段の行頭）の 1pt 手前へ寄せる。
        # 右段の行頭だけを候補にする（行の先頭の語＝同じ高さでそれより左に語が無いもの）。左段の行の後半の語を拾わない。
        right_x0 = [
            w["x0"]
            for w in words
            if w["x0"] >= gutter - 1
            and not any(
                abs(v["top"] - w["top"]) <= y_tol and gutter - 1 <= v["x0"] < w["x0"] for v in words
            )
            and not any(
                abs(v["top"] - w["top"]) <= y_tol and v["x0"] < gutter - 1 and v["x1"] > gutter - 1
                for v in words
            )
        ]
        if right_x0:
            gutter = max(gutter, min(right_x0) - 2)

    left, right, span = [], [], []
    for w in words:
        if w["x1"] <= gutter + 1:
            left.append(w)
        elif w["x0"] >= gutter - 1:
            right.append(w)
        else:
            span.append(w)

    if words and len(span) / len(words) > span_ratio_max:
        # 全幅の図/表がページを占める。段分割すると壊れるので 1 段で読む
        return _cluster_words_to_lines(words, y_tol), None, 1

    # **右寄せフィールドを「第 2 段」と誤認しないこと。**
    # 目次ページは「見出し ……… ページ番号」の形で、番号欄が gutter の右に来る。
    # 真の 2 段組は両側の文字量が同程度だが、右寄せフィールドは極端に少ない。
    # 実測：目次ページを 2 段と誤認し、ページ番号が全部末尾に集まった（p4 CER 0.38）。
    n_left = sum(len(w["text"]) for w in left)
    n_right = sum(len(w["text"]) for w in right)
    if max(n_left, n_right) > 0:
        ratio = min(n_left, n_right) / max(n_left, n_right)
        if ratio < 0.15:
            return _cluster_words_to_lines(words, y_tol), None, 1

    lleft = _cluster_words_to_lines(left, y_tol)
    lright = _cluster_words_to_lines(right, y_tol)
    lspan = _cluster_words_to_lines(span, y_tol)

    def top_of(ln: list[dict]) -> float:
        return min(w["top"] for w in ln)

    # spanning 行の y でゾーンを切る
    bounds = sorted(top_of(s) for s in lspan)
    zones: list[tuple[float, float]] = []
    prev = -1e9
    for b in bounds:
        zones.append((prev, b))
        prev = b
    zones.append((prev, 1e9))

    span_by_top = {top_of(s): s for s in lspan}
    out: list[list[dict]] = []
    for zi, (z0, z1) in enumerate(zones):
        if zi > 0:
            # ゾーンの開始境界にある spanning 行を先に出す
            out.append(span_by_top[bounds[zi - 1]])
        zl = sorted([ln for ln in lleft if z0 < top_of(ln) <= z1], key=top_of)
        zr = sorted([ln for ln in lright if z0 < top_of(ln) <= z1], key=top_of)
        out.extend(zl)
        out.extend(zr)
    return out, gutter, 2


def _join_words(words: list[dict]) -> str:
    """語を連結する。**CJK 同士には空白を入れない**。

    空白を入れるのは ASCII 単語同士の間だけ。
    """

    def is_ascii_word(s: str) -> bool:
        return bool(s) and all(ord(c) < 128 for c in s)

    out = ""
    for i, w in enumerate(words):
        t = w["text"]
        if i == 0:
            out = t
            continue
        prev = words[i - 1]["text"]
        if is_ascii_word(prev[-1:]) and is_ascii_word(t[:1]):
            out += " " + t
        else:
            out += t
    return out


def _rect_boxes(rects: list[dict], min_w: float = 20, min_h: float = 8) -> list[list[float]]:
    return [
        [r["x0"], r["top"], r["x1"], r["bottom"]]
        for r in rects
        if (r["x1"] - r["x0"]) >= min_w and (r["bottom"] - r["top"]) >= min_h
    ]


def _box_area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _overlap_area(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy


def _overlaps_any(box: list[float], others: list[list[float]], frac: float) -> bool:
    """box の面積のうち others と重なる割合が frac 以上なら True。"""
    area = _box_area(box)
    if area <= 0:
        return False
    cover = sum(_overlap_area(box, o) for o in others)
    return (cover / area) >= frac


def _merge_boxes(boxes: list[list[float]], gap: float = 6.0) -> list[list[float]]:
    """重なる/近接する矩形を結合して領域にまとめる。素朴な反復結合。"""
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for b in boxes:
            hit = None
            for o in out:
                if (
                    b[0] <= o[2] + gap
                    and o[0] <= b[2] + gap
                    and b[1] <= o[3] + gap
                    and o[1] <= b[3] + gap
                ):
                    hit = o
                    break
            if hit is None:
                out.append(b)
            else:
                hit[0] = min(hit[0], b[0])
                hit[1] = min(hit[1], b[1])
                hit[2] = max(hit[2], b[2])
                hit[3] = max(hit[3], b[3])
                changed = True
        boxes = out
    return boxes


def _grow_to_words(
    box: list[float], words: list[dict], pad: float = 24.0, rounds: int = 4
) -> list[float]:
    """箱の近傍にある語を取り込むまで箱を広げる。

    語の**中心**が箱を `pad` だけ広げた範囲に入っていれば、その語を含むように箱を
    拡張する。中心で判定するのは、端がわずかに掛かるだけの本文行を巻き込まないため。
    拡張すると新たな語が範囲に入るので、変化が止まるまで繰り返す（上限 `rounds`）。
    """
    b = list(box)
    for _ in range(rounds):
        changed = False
        for w in words:
            cx = (w["x0"] + w["x1"]) / 2
            cy = (w["top"] + w["bottom"]) / 2
            if b[0] - pad <= cx <= b[2] + pad and b[1] - pad <= cy <= b[3] + pad:
                nb = [
                    min(b[0], w["x0"]),
                    min(b[1], w["top"]),
                    max(b[2], w["x1"]),
                    max(b[3], w["bottom"]),
                ]
                if nb != b:
                    b = nb
                    changed = True
        if not changed:
            break
    return b


def _column_bands(lines: list[Line], page_w: float) -> list[list[float]]:
    """行の x 範囲から段の帯を推定する。x0 のヒストグラムの谷で分ける素朴版。"""
    if not lines:
        return []
    xs = sorted(ln.x0 for ln in lines)
    # 中央付近に大きな空隙があれば 2 段と見る
    mid = page_w / 2
    left = [x for x in xs if x < mid]
    right = [x for x in xs if x >= mid]
    if len(left) >= 5 and len(right) >= 5:
        lmax = max(ln.x1 for ln in lines if ln.x0 < mid)
        rmin = min(ln.x0 for ln in lines if ln.x0 >= mid)
        if rmin - lmax > 8:
            return [[min(left), lmax], [rmin, max(ln.x1 for ln in lines)]]
    return [[min(xs), max(ln.x1 for ln in lines)]]


def _is_contract(cached: list[dict]) -> bool:
    """1 ページ目の語から契約書かを判定する（structure.contract.detect_contract_scheme と同じ印字形）。

    幾何の段階ではまだ行を組んでいないので、上から順の語を行の近似として使う。約款では False になり、
    図領域の手順は移植元のまま変わらない。
    """
    from .structure.contract import detect_contract_scheme

    if not cached:
        return False
    ws = sorted(cached[0]["words"], key=lambda w: (round(w["top"]), w["x0"]))
    rows: list[str] = []
    top = None
    for w in ws:
        if top is None or abs(w["top"] - top) > 2:
            rows.append(w["text"])
            top = w["top"]
        else:
            rows[-1] += w["text"]
    return detect_contract_scheme(rows) is not None


def extract_geometry(doc_id: str) -> tuple[list[Line], list[PageGeom]]:
    """PDF から行 bbox・フォント・描画オブジェクトを取り出す。"""
    lines: list[Line] = []
    pages: list[PageGeom] = []
    with pdfplumber.open(doc_pdf(doc_id)) as pdf:
        # --- パス 1：全ページの語を読み、文書全体の gutter を決める ---
        cached: list[dict] = []
        for page in pdf.pages:
            cached.append(
                {
                    "words": page.extract_words(
                        extra_attrs=["fontname", "size"], keep_blank_chars=False
                    ),
                    "width": float(page.width),
                    "height": float(page.height),
                    "rects": page.rects or [],
                    "curves": page.curves or [],
                    "lines": page.lines or [],
                    # 表領域は pdfplumber の罫線ベース表検出に任せる。
                    # **実測（S3）**：自作の「矩形を結合する」方式は表の外枠まで
                    # まとまらず、1 行ぶんの断片しか返さなかった。gold の
                    # `tbl_definitions` に対する最良 IoU は 0.078。
                    # `find_tables()` は同じページで **0.994**。
                    # 理由：この体裁の表はセルを塗り矩形で描かず、罫線を line
                    # オブジェクトとして引く。矩形だけを見ると表の骨格が見えない。
                    # bbox とセル数を対で持つ。セル数は P3 の `max_tokens` 算出に使う
                    # （F12/F14：`max_tokens = セル数 × 46`。足りないと大きい表が
                    # 途中切断され cell F1 が 0 になる）。
                    "table_bboxes": [
                        {"bbox": list(t.bbox), "n_cells": len(t.cells or [])}
                        for t in page.find_tables()
                    ],
                }
            )
        doc_g = document_gutter([(c["words"], c["width"], c["height"]) for c in cached])
        contract = _is_contract(cached)

        # --- パス 2：文書 gutter を適用して読み順を決める ---
        for pi, c in enumerate(cached, start=1):
            page = c
            words = c["words"]
            wl, gutter, n_cols = lines_in_reading_order(
                words, c["width"], c["height"], gutter=doc_g, snap_gutter=contract
            )
            page_lines: list[Line] = []
            for li, ws in enumerate(wl):
                text = _join_words(ws)
                if not text.strip():
                    continue
                sizes = [w.get("size") for w in ws if w.get("size")]
                fonts = [w.get("fontname") for w in ws if w.get("fontname")]
                x0 = min(w["x0"] for w in ws)
                x1 = max(w["x1"] for w in ws)
                y0 = min(w["top"] for w in ws)
                y1 = max(w["bottom"] for w in ws)
                n_chars = sum(len(w["text"]) for w in ws)
                char_w = (x1 - x0) / n_chars if n_chars else None
                page_lines.append(
                    Line(
                        doc_id=doc_id,
                        page=pi,
                        line_no=li,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                        text=text,
                        font=statistics.mode(fonts) if fonts else None,
                        size=round(statistics.mode(sizes), 2) if sizes else None,
                        char_w=round(char_w, 3) if char_w else None,
                    )
                )
            lines.extend(page_lines)

            rects = page["rects"]
            curves = page["curves"]
            line_objs = page["lines"]
            # 表：pdfplumber の罫線ベース表検出（上の実測コメント参照）。
            # 座標は pdfplumber 流儀で **上原点**（`top`/`bottom` と同じ系）。
            _tsrc = page["table_bboxes"]
            tb = _merge_boxes([t["bbox"] for t in _tsrc], gap=2.0) if _tsrc else []
            # 結合後の領域に、元の表のセル数を合算して割り当てる
            tb_cells = []
            for b in tb:
                n = sum(
                    t["n_cells"]
                    for t in _tsrc
                    if _overlap_area(b, t["bbox"]) > 0.5 * _box_area(t["bbox"])
                )
                tb_cells.append(int(n))
            # 図：**点線リーダーのダッシュを図と誤認しないこと。**
            # 目次ページは「……」が 1 本 2.3pt の line オブジェクト数千本として現れる
            # （実測：p4 で 6,581 本、すべて幅 2.3pt / 高さ 0）。長さで濾す。
            MIN_SEG = 5.0
            fig_src = [
                [o["x0"], o["top"], o["x1"], o["bottom"]]
                for o in (line_objs + curves)
                if max(o["x1"] - o["x0"], o["bottom"] - o["top"]) >= MIN_SEG
            ]
            if contract:
                # **契約書の図領域（C-003）。** 約款の手順のままだと、表の罫線と図の線が語を介して 1 つの箱に
                # 合体し（sys-0004 p4：ページの 8 割）、署名欄の下線が図になる（dev：gold 64 図に対し予測 260 箱・
                # 偽 196）。表の箱の内側の線と、横線だけの塊を図の材料から外し、語の取り込みも表の外に限る。
                fig_src = [b for b in fig_src if not _overlaps_any(b, tb, 0.5)]
                words = [
                    w
                    for w in words
                    if not _overlaps_any([w["x0"], w["top"], w["x1"], w["bottom"]], tb, 0.5)
                ]
            fb = _merge_boxes(fig_src, gap=14.0) if fig_src else []
            if contract:
                fb = [
                    b for b in fb if (b[3] - b[1]) >= 12.0
                ]  # 横線だけの塊（下線・区切り線）は図ではない
            # **図の箱をラベル文字まで広げる。** 図のノード名は line/curve ではなく
            # テキストなので、ストロークだけの箱には収まらない。実測（S3・PILOT 5 文書
            # の gold 図 15 件に対する「gold 領域がクロップに収まっている割合」）：
            #   pad=0  中央値 0.671 / 完全包含 0.00
            #   pad=16 中央値 0.740 / 完全包含 0.20
            #   pad=20 中央値 0.932 / 完全包含 0.67
            #   pad=24 中央値 0.987 / 完全包含 0.87   ← 採用
            #   pad=28 中央値 0.990 / 完全包含 0.93（ただしページ面積比の中央値が
            #          0.31 → 0.36 に増え、本文を飲み込み始める）
            # 結合間隔（gap）を 14→48 に広げても包含は 0.671 で動かなかった。
            # **足りなかったのは距離ではなく「文字を図の一部として数えること」だった。**
            if fb:
                # C-003 ラウンド 2：契約書だけ取り込みを 6pt にすると偽の箱 159 → 39・面積比 3.2 → 0.55 になったが、
                # 図の下の目盛り・ラベルが落ちて包含率の中央値が 0.95 → 0.55 に下がった（図の読み取りを壊す）。
                # 打ち切り（2 ラウンド）に従い、包含率を保つ 24pt（移植元の値）のまま凍結した
                fb = _merge_boxes([_grow_to_words(b, words) for b in fb], gap=2.0)
            # 表の矩形と大きく重なる領域は表であって図ではない
            fb = [b for b in fb if not _overlaps_any(b, tb, 0.5)]
            # 面積が小さいものは装飾罫線。図として扱わない
            fb = [b for b in fb if (b[2] - b[0]) * (b[3] - b[1]) >= 2000.0]
            cw = [ln.char_w for ln in page_lines if ln.char_w]
            pages.append(
                PageGeom(
                    doc_id=doc_id,
                    page=pi,
                    width=c["width"],
                    height=c["height"],
                    n_lines=len(page_lines),
                    n_rects=len(rects),
                    n_curves=len(curves),
                    n_line_objs=len(line_objs),
                    table_boxes=tb,
                    table_cells=tb_cells,
                    figure_boxes=fb,
                    column_bands=(
                        [[0.0, gutter], [gutter, c["width"]]]
                        if gutter is not None
                        else [[0.0, c["width"]]]
                    ),
                    mean_char_w=round(statistics.median(cw), 3) if cw else None,
                    gutter=round(gutter, 2) if gutter is not None else None,
                    n_cols=n_cols,
                )
            )
    return lines, pages


def geom_paths(doc_id: str) -> tuple[Path, Path]:
    d = WORK / "geometry"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{doc_id}.lines.jsonl", d / f"{doc_id}.pages.jsonl"


def write_geometry(doc_id: str) -> tuple[int, int]:
    lines, pages = extract_geometry(doc_id)
    lp, pp = geom_paths(doc_id)
    with lp.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(asdict(ln), ensure_ascii=False) + "\n")
    with pp.open("w", encoding="utf-8") as f:
        for pg in pages:
            f.write(json.dumps(asdict(pg), ensure_ascii=False) + "\n")
    return len(lines), len(pages)


def read_lines(doc_id: str) -> list[Line]:
    lp, _ = geom_paths(doc_id)
    out = []
    with lp.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(Line(**json.loads(line)))
    return out


def read_pages(doc_id: str) -> list[PageGeom]:
    _, pp = geom_paths(doc_id)
    out = []
    with pp.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(PageGeom(**json.loads(line)))
    return out

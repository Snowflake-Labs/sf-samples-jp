"""段 A：PDF の読み取り → pdoc（計算用の文書表現）。

予測側のモジュールである。開くのは渡された PDF だけで、正解を開かない。

契約書向けに足した規則（RE_CT_PARA・RE_FORM_CHAP・RE_FORM_ART と、それを使う分岐）は、契約書の体裁
（contract_scheme.detect_contract_scheme）が判定されたときだけ働き、約款の読み取りには影響しない。

入力は段 R の幾何（`geometry.py`：段を考慮した読み順の行・フォント・大きさ）と、pdfplumber の描画要素
（罫線・矩形・曲線）である。出力は条・項・号・表・図・算式・囲みの木（後段の候補検出・カード合成の入力）。

- 見出し：太字の行で、ラベル（第N編・第N章・第N節・第N条（…）・別表N・付表N・第N・…特約）を持つもの。
  構造の読み取りの木は、柱に出る章題と本文の章見出しを取り違えて章を落としたので使わない。
- 段落・号：行頭のラベル（（N）・(N)・N．・①…）、無番号の段落は前行の句点と字下げで切る。
- 表：pdfplumber の罫線表（find_tables）。○×だけの格子は図（matrix）にする。
- 算式：罫の箱が 1 行に並び「＝」と演算子を含む行。
- 囲み：薄い塗りの矩形。数値と「とき／場合」を含む囲みは設例（id の末尾 `_note`）。
- 脚注：小さい字の「（*N）」で始まる行。
- 図：ベクトルの図形（曲線・線・矢じり）とテキスト層のラベルから決定的に組む（flowchart・timeline・matrix）。
  facts（文章の説明）は組んだ図から機械的に作る（印刷された内容だけから）。
- 値スパン：本文・脚注・囲み・算式・図のラベルの数値表記を `{const:vNNN}` に置き換え、表記を `meta.constants` に置く。
  LLM は値を書き写さず、キーで指す。解析できない数値表記は置き換えず `value_span_errors` に残す。
  年月日の日付は値スパンにせず逐語のまま残し（`n_dates_kept`）、漢数字の数値表記は数えるだけにする（`n_kanji_values`）。
- 各単位に出所（ページ・bbox・行）を `src` として持つ（採点側の対応付けと、精読 V に使う）。
"""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import defaultdict
from pathlib import Path

import pdfplumber

from ..common import numparse as N
from ..common.tunables import tun
from .contract_scheme import KANJI, KANJI_NUM, detect_contract_scheme
from .furniture import detect_furniture
from .geometry import Line, extract_geometry, table_settings

SCHEMA = "pdoc-1"

# ---------------------------------------------------------------- 正規表現

_D = r"[0-9０-９]+"
RE_PART = re.compile(rf"^第{_D}編")
RE_CHAP = re.compile(rf"^第{_D}章")
RE_SEC = re.compile(rf"^第{_D}節")
RE_ART = re.compile(rf"^第{_D}条(の{_D})?[（(]")
RE_APPX = re.compile(rf"^(別表|付表){_D}")
RE_APPXSEC = re.compile(rf"^第{_D}(?![0-9０-９条章節編款])")
RE_RIDER = re.compile(r"特約(条項)?$")
RE_PLABEL = re.compile(rf"^(（{_D}）|\({_D}\)|{_D}[．.](?![0-9０-９])|[①-⑳])")
RE_FN = re.compile(r"^([（(][*＊※注]\s*[0-9０-９]+[）)]|[❶-❿])")
RE_FN_HEAD = re.compile(rf"^第{_D}条備考$")
RE_TABCAP = re.compile(rf"^表{_D}")
RE_FIGCAP = re.compile(rf"^図{_D}")
RE_FORMULA_OP = re.compile(r"[×÷＋－−+]")
RE_TOC_TAIL = re.compile(r"[0-9０-９]{1,3}$")
# 契約書だけで使う印字形（約款の読み取りには使わない）
# 項の番号：行頭の 1〜2 桁の数字に、数字・単位・区切りでない文字が続く（「２本件検討は、…」）
RE_CT_PARA = re.compile(
    r"^([0-9０-９]{1,2})(?=[^0-9０-９,，.．:：％%年月日時分円条項号章節万千百億か箇ヶカ])"
)
# 様式型の見出し：章「1用語の意味」（太字・本文より大きい）と条「(1)用語」（太字）
RE_FORM_CHAP = re.compile(r"^([0-9０-９]{1,2})(?![0-9０-９])([^\s、。0-9０-９]\S{0,30})$")
RE_FORM_ART = re.compile(r"^([（(][0-9０-９]{1,2}[）)])([^\s、。]\S{0,30})$")
_Z2H_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")
MARKS = set("○×△◎●－-ー")

_NUM = r"[0-9０-９][0-9０-９,，.．]*"
_UNIT = r"(?:営業日|日|か月|ヶ月|カ月|箇月|年|％|%|割|倍|回|名|人|時間|分|キロメートル|km|歳|級|台|個|件)"
RE_PAY_VERDICT = re.compile(
    r"支払(い)?ません|支払わない|お支払いしません|支払います|お支払いします"
)
RE_PAY_NEG = re.compile(r"支払(い)?ません|支払わない|お支払いしません")
RE_VALUE = re.compile(
    rf"(?<![第0-9０-９,，.．])(?=[0-9０-９])(?:{_NUM}億)?(?:{_NUM}万)?(?:{_NUM}千)?(?:{_NUM})?円"
    rf"|(?<![第0-9０-９,，.．]){_NUM}{_UNIT}"
)
# 年月日の日付（西暦・和暦・全角数字）・年月・月日。数値の値スパンにせず逐語のまま残す。
# 計算仕様の定数は整数だけなので日付は定数にできず、「2026年」「1日」を年数・日数の定数と取り違えるため
_DD = r"[0-9０-９]{1,2}"
RE_DATE = re.compile(
    # 西暦の年は前に数字が続いても日付として取る（奥付の「様式Ｓ２６１００２2026年10月1日」のように、
    # 様式の番号と日付が区切りなく並ぶ文書がある）
    rf"(?:(?:令和|平成|昭和)(?:[0-9０-９]{{1,2}}|元)|[0-9０-９]{{4}})年{_DD}月(?:{_DD}日)?"
    rf"|(?<![0-9０-９]){_DD}月{_DD}日"
    # 年だけ（和暦の年・西暦 4 桁の年。年度を含む）。4 桁の年数の期間は約款・契約書に出ない
    r"|(?:令和|平成|昭和)(?:[0-9０-９]{1,2}|元)年度?"
    r"|(?<![0-9０-９])[0-9０-９]{4}年度?"
)
# 漢数字の数値表記（十万円・三十日など）。値スパンにしない（数値のパーサが扱わない）が、件数は数えて残す
RE_KANJI_VALUE = re.compile(
    r"(?<!第)[〇一二三四五六七八九十百千万億]{1,8}"
    r"(?:円|か月|ヶ月|カ月|箇月|日|年|％|割|倍|回|名|人|時間|歳)"  # 「分」は十分・三分の一と紛れるので数えない
)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def compact(s: str) -> str:
    return "".join(nfkc(s).split())


def is_bold(ln: Line) -> bool:
    f = ln.font or ""
    return "Bold" in f or "bold" in f or "Heavy" in f or "Black" in f


def _cjk_join(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out and re.match(r"[A-Za-z0-9]", out[-1]) and re.match(r"[A-Za-z0-9]", p[0]):
            out += " "
        out += p
    return out


def _center(b) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _inside(pt, b, pad=0.0) -> bool:
    return b[0] - pad <= pt[0] <= b[2] + pad and b[1] - pad <= pt[1] <= b[3] + pad


def _line_box(ln: Line) -> list[float]:
    return [ln.x0, ln.y0, ln.x1, ln.y1]


def _union(boxes):
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


# ---------------------------------------------------------------- 値スパン


class Values:
    """数値表記 → {const:vNNN}。同じ表記には同じキーを振る（ラベルの照合を安定させる）。"""

    def __init__(self):
        self.constants: dict[str, str] = {}
        self.by_text: dict[str, str] = {}
        self.errors: list[dict] = []
        self.n_spans = 0
        self.n_dates = 0  # 値スパンにしなかった日付の数
        self.n_kanji = 0  # 値スパンにしなかった漢数字の数値表記の数

    def sub(self, text: str, where: str) -> str:
        """日付は逐語のまま残し、その間の部分の数値表記を値スパンにする。"""
        text = text or ""
        self.n_kanji += len(RE_KANJI_VALUE.findall(text))
        out, pos = [], 0
        for m in RE_DATE.finditer(text):
            out.append(self._sub_values(text[pos : m.start()], where))
            out.append(m.group(0))
            self.n_dates += 1
            pos = m.end()
        out.append(self._sub_values(text[pos:], where))
        return "".join(out)

    def _sub_values(self, text: str, where: str) -> str:
        def rep(m):
            s = m.group(0)
            try:
                N.parse(s)
            except N.NumParseError as e:
                self.errors.append({"text": s, "where": where, "error": str(e)})
                return s
            k = self.by_text.get(s)
            if k is None:
                k = f"v{len(self.constants) + 1:03d}"
                self.constants[k] = s
                self.by_text[s] = k
            self.n_spans += 1
            return "{const:" + k + "}"

        return RE_VALUE.sub(rep, text)


# ---------------------------------------------------------------- 描画要素


def _fill_lum(obj) -> float | None:
    c = obj.get("non_stroking_color")
    if c is None:
        return None
    if isinstance(c, (int, float)):
        return float(c)
    c = list(c)
    if len(c) == 1:
        return float(c[0])
    if len(c) == 3:
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    if len(c) == 4:
        return 1.0 - min(1.0, c[3] + 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2])
    return None


class PageGraphics:
    def __init__(self, page):
        self.page = page
        self.rects = [r for r in page.rects]
        self.lines = [ln for ln in page.lines]
        self.curves = [c for c in page.curves]
        self.words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        self.formula_terms: dict[tuple, list] = {}
        self.errors: list[str] = []
        try:
            found = page.find_tables(table_settings())
        except Exception as e:  # noqa: BLE001 — 失敗はページの errors に残し、pdoc.read_errors で数える
            self.errors.append(f"find_tables: {type(e).__name__}: {e}")
            found = []
        self.tables = [t for t in found if len(t.rows) >= 2]
        for t in found:
            if len(t.rows) == 1:
                ext = self._extend_header_table(page, t)
                if ext is not None:
                    self.tables.append(ext)

    def _extend_header_table(self, page, t):
        """罫で囲んだ見出し行だけの表＋下に横罫だけの本体（縦罫なし）を、見出しのセルの境で区切って読む。"""
        x0, top, x1, bottom = t.bbox
        segs: dict[float, list[tuple[float, float]]] = defaultdict(list)
        for ln in self.lines:
            if abs(ln["top"] - ln["bottom"]) < 1 and ln["top"] > bottom - 1:
                segs[round(ln["top"], 1)].append((ln["x0"], ln["x1"]))
        rules = []
        for y, ss in segs.items():
            cov, cur = 0.0, x0
            for a, b in sorted(ss):
                if a <= cur + 2 and b > cur:
                    cov += b - max(a, cur)
                    cur = b
            if cov >= (x1 - x0) - tun("pdoc.header_rule_cov_tol", 6):
                rules.append(y)
        rules.sort()
        ys = [top, bottom]
        for y in rules:
            if y - ys[-1] <= tun("pdoc.header_rule_gap", 60):
                ys.append(y)
            else:
                break
        if len(ys) < 4:
            return None
        xs = sorted(
            {round(c[0], 1) for c in t.rows[0].cells if c}
            | {round(c[2], 1) for c in t.rows[0].cells if c}
        )
        try:
            ts = page.find_tables(
                table_settings={
                    "vertical_strategy": "explicit",
                    "horizontal_strategy": "explicit",
                    "explicit_vertical_lines": xs,
                    "explicit_horizontal_lines": ys,
                }
            )
        except Exception as e:  # noqa: BLE001
            self.errors.append(f"find_tables(explicit): {type(e).__name__}: {e}")
            return None
        return ts[0] if ts and len(ts[0].rows) >= 2 else None

    def formula_groups(self, exclude: list[list[float]]) -> list[list[float]]:
        """算式：罫の箱（高さ 12〜30pt）を縦に近いもの同士でまとめ、語に「＝」を含む塊。"""
        min_h, max_h = tun("pdoc.formula_min_h", 12), tun("pdoc.formula_max_h", 48)
        min_w = tun("pdoc.formula_min_w", 15)
        vgap, hslack = tun("pdoc.formula_vgap", 24), tun("pdoc.formula_hslack", 40)
        wpad = tun("pdoc.formula_word_pad", 30)
        boxes = []
        for r in self.rects:
            w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
            b = [r["x0"], r["top"], r["x1"], r["bottom"]]
            inner = [
                wd
                for wd in self.words
                if _inside(_center([wd["x0"], wd["top"], wd["x1"], wd["bottom"]]), b)
            ]
            if not inner or re.search(r"。(?![）)])", "".join(wd["text"] for wd in inner)):
                continue  # 文（句点）を含む箱は算式の項ではない（囲み・脚注の枠）
            if (
                min_h <= h <= max_h
                and min_w <= w
                and not any(_inside(_center(b), e) for e in exclude)
            ):
                if not any(
                    abs(b[0] - o[0]) < 2.5 and abs(b[1] - o[1]) < 2.5 and abs(b[2] - o[2]) < 2.5
                    for o in boxes
                ):
                    boxes.append(b)
        groups: list[list[list[float]]] = []
        for b in sorted(boxes, key=lambda b: (b[1], b[0])):
            for gp in groups:
                u = _union(gp)
                if (
                    b[1] - u[3] <= vgap
                    and b[1] >= u[1] - 2
                    and not (b[2] < u[0] - hslack or b[0] > u[2] + hslack)
                ):
                    gp.append(b)
                    break
            else:
                groups.append([b])
        out = []
        for gp in groups:
            gp = self._trim_formula(gp)
            if not gp:
                continue
            u = _union(gp)
            ws = [
                w
                for w in self.words
                if _inside(
                    _center([w["x0"], w["top"], w["x1"], w["bottom"]]),
                    [u[0] - wpad, u[1], u[2] + wpad, u[3]],
                    1,
                )
            ]
            txt = "".join(w["text"] for w in ws)
            if ("＝" in txt or "=" in txt) and (len(gp) >= 2):
                xs = [w["x0"] for w in ws] + [w["x1"] for w in ws]
                out.append([min([u[0]] + xs) - 2, u[1] - 1, max([u[2]] + xs) + 2, u[3] + 1])
                self.formula_terms[tuple(out[-1])] = gp
        return out

    def formula_text(self, box: list[float]) -> str:
        """算式を行ごと・左から読む。項の箱の直下にある箱の外の語は分母（（分子÷分母））として読む。"""
        gp = self.formula_terms.get(tuple(box))
        ws = [
            w
            for w in self.words
            if _inside(_center([w["x0"], w["top"], w["x1"], w["bottom"]]), box, 1)
        ]
        if not gp:
            return _label_of(ws)
        rows: list[list[list[float]]] = []
        for b in sorted(gp, key=lambda b: (b[1], b[0])):
            if rows and min(_union(rows[-1])[3], b[3]) - max(_union(rows[-1])[1], b[1]) > 0.3 * (
                b[3] - b[1]
            ):
                rows[-1].append(b)
            else:
                rows.append([b])
        texts: dict[int, str] = {}
        used = set()
        for k, b in enumerate(gp):
            inb = [
                w for w in ws if _inside(_center([w["x0"], w["top"], w["x1"], w["bottom"]]), b, 0.5)
            ]
            used.update(id(w) for w in inb)
            texts[k] = _label_of(inb)
        for w in ws:
            if id(w) in used:
                continue
            for k, b in enumerate(gp):
                ov = min(w["x1"], b[2]) - max(w["x0"], b[0])
                if ov > 0.5 * (w["x1"] - w["x0"]) and -1 <= w["top"] - b[3] <= 8:
                    texts[k] = f"（{texts[k]}÷{w['text']}）"
                    used.add(id(w))
                    break
        items = [(k, b, texts[k]) for k, b in enumerate(gp)]
        loose = [w for w in ws if id(w) not in used]
        out = []
        for row in rows:
            u = _union(row)
            its = [(b[0], t) for k, b, t in items if b in row]
            its += [
                (w["x0"], w["text"])
                for w in loose
                if u[1] - 4 <= (w["top"] + w["bottom"]) / 2 <= u[3] + 4
            ]
            out.append("".join(t for _, t in sorted(its)))
        rest = [
            w
            for w in loose
            if not any(
                _union(r)[1] - 4 <= (w["top"] + w["bottom"]) / 2 <= _union(r)[3] + 4 for r in rows
            )
        ]
        return "".join(out) + _label_of(rest)

    def _trim_formula(self, gp: list[list[float]]) -> list[list[float]]:
        """箱の塊を行に分け、「＝」のある行で終える（「＝」が行末なら結果の箱の次の行まで）。"""
        rows: list[list[list[float]]] = []
        for b in sorted(gp, key=lambda b: (b[1], b[0])):
            if rows and (
                abs(rows[-1][0][1] - b[1]) < 4
                or min(_union(rows[-1])[3], b[3]) - max(_union(rows[-1])[1], b[1])
                > 0.3 * (b[3] - b[1])
            ):
                rows[-1].append(b)
            else:
                rows.append([b])
        for i, row in enumerate(rows):
            u = _union(row)
            nxt = rows[i + 1][0][1] if i + 1 < len(rows) else u[3] + 2
            eq = [
                w
                for w in self.words
                if ("＝" in w["text"] or "=" in w["text"])
                and u[1] - 2 <= (w["top"] + w["bottom"]) / 2 <= max(u[3] + 2, nxt - 1)
                and u[0] - 30 <= w["x0"] <= u[2] + 30
            ]
            if eq:
                last_eq = max(w["x1"] for w in eq)
                between = all((w["top"] + w["bottom"]) / 2 > u[3] for w in eq)
                ends_row = between or all(b[0] < last_eq for b in row)
                keep = rows[: i + 2] if ends_row and i + 1 < len(rows) else rows[: i + 1]
                return [b for r in keep for b in r]
        return []

    def framed_boxes(self, exclude: list[list[float]]) -> list[list[float]]:
        """罫で囲んだ囲み（塗りなし）。表・算式・図の中のもの、高さ 30pt 以下のものは除く。"""
        bs = []
        for r in self.rects:
            w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
            lum = _fill_lum(r)
            filled_dark = r.get("fill") and lum is not None and lum < 0.86
            b = [r["x0"], r["top"], r["x1"], r["bottom"]]
            # 枠：線で描いたもの、または外形と内側の穴で描いた濃い塗り（中に語がある＝塗りつぶしではない）
            frame = (r.get("stroke") and not filled_dark) or (
                filled_dark
                and any(
                    _inside(_center([wd["x0"], wd["top"], wd["x1"], wd["bottom"]]), b)
                    for wd in self.words
                )
            )
            if frame and w > tun("pdoc.frame_min_w", 80) and h > tun("pdoc.frame_min_h", 30):
                if any(_overlap(b, e) and _inside(_center(b), e) for e in exclude):
                    continue
                inner = [
                    c
                    for c in self.curves
                    if _inside(_center([c["x0"], c["top"], c["x1"], c["bottom"]]), b)
                ]
                if len(inner) >= 3:
                    continue
                bs.append(b)
        out: list[list[float]] = []
        for b in sorted(bs, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
            if not any(_inside(_center(b), o, 2) for o in out):
                out.append(b)
        return out

    def light_boxes(self) -> list[list[float]]:
        """薄い塗りの矩形（囲み）。重なるものはまとめる。"""
        bs = []
        for r in self.rects:
            w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
            lum = _fill_lum(r)
            if (
                r.get("fill")
                and lum is not None
                and tun("pdoc.light_lum_lo", 0.86) <= lum < 0.995
                and w > tun("pdoc.light_min_w", 60)
                and h > tun("pdoc.light_min_h", 14)
            ):
                bs.append([r["x0"], r["top"], r["x1"], r["bottom"]])
        out: list[list[float]] = []
        for b in sorted(bs, key=lambda b: (b[1], b[0])):
            for o in out:
                if _overlap(o, [b[0] + 2, b[1] + 2, b[2] - 2, b[3] - 2]):
                    o[:] = _union([o, b])
                    break
            else:
                out.append(list(b))
        return out


# ---------------------------------------------------------------- 図（ベクトル）


def _pts(c):
    return [(float(x), float(y)) for x, y in c.get("pts", [])]


def _is_arrowhead(c) -> bool:
    w, h = c["x1"] - c["x0"], c["bottom"] - c["top"]
    return bool(c.get("fill")) and len(c.get("pts", [])) <= 5 and w <= 8 and h <= 8


def _shape_kind(c) -> str:
    pts = _pts(c)
    w, h = c["x1"] - c["x0"], c["bottom"] - c["top"]
    if len(pts) == 5 and w > 20 and h > 10:
        cx, cy = _center([c["x0"], c["top"], c["x1"], c["bottom"]])
        tops = [p for p in pts if abs(p[0] - cx) < 3]
        if len(tops) >= 2:
            return "decision"
    if len(pts) >= 6 and w > 20 and h > 10:
        return "terminal"
    if w > 20 and h > 10:
        return "process"
    return "other"


def _words_in(words, box, pad=1.5):
    return [
        w for w in words if _inside(_center([w["x0"], w["top"], w["x1"], w["bottom"]]), box, pad)
    ]


def _label_of(words) -> str:
    rows: dict[int, list] = defaultdict(list)
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        key = None
        for k in rows:
            if abs(k - w["top"]) < 3:
                key = k
                break
        rows[key if key is not None else round(w["top"])].append(w)
    return _cjk_join(
        [
            "".join(x["text"] for x in sorted(r, key=lambda w: w["x0"]))
            for _, r in sorted(rows.items())
        ]
    )


def _dist_pt_seg(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def read_flowchart(g: PageGraphics, box) -> dict | None:
    """矢印でつないだ図形の図。ノード＝図形（菱形＝判定・角丸＝端点・矩形＝処理）、辺＝矢印、辺のラベル＝小さな囲みの語。"""
    curves = [
        c for c in g.curves if _inside(_center([c["x0"], c["top"], c["x1"], c["bottom"]]), box, 2)
    ]
    rects = [
        r for r in g.rects if _inside(_center([r["x0"], r["top"], r["x1"], r["bottom"]]), box, 2)
    ]
    segs = [
        ln
        for ln in g.lines
        if _inside(_center([ln["x0"], ln["top"], ln["x1"], ln["bottom"]]), box, 2)
    ]
    words = _words_in(g.words, box, 2)
    heads = [c for c in curves if _is_arrowhead(c)]
    shapes = []
    for c in curves:
        if _is_arrowhead(c) or not c.get("fill"):
            continue
        k = _shape_kind(c)
        if k != "other":
            shapes.append((k, [c["x0"], c["top"], c["x1"], c["bottom"]]))
    small_rects = []
    for r in rects:
        w, h = r["x1"] - r["x0"], r["bottom"] - r["top"]
        b = [r["x0"], r["top"], r["x1"], r["bottom"]]
        if w > 20 and h > 12 and not any(_overlap(b, s[1]) for s in shapes):
            shapes.append(("process", b))
        elif w <= 30 and h <= 12:
            small_rects.append(b)
    # 同じ形の二重描画を除く
    uniq = []
    for k, b in shapes:
        if not any(
            abs(b[0] - u[1][0]) < 2 and abs(b[1] - u[1][1]) < 2 and abs(b[2] - u[1][2]) < 2
            for u in uniq
        ):
            uniq.append((k, b))
    shapes = uniq
    if len(shapes) < 2:
        return None
    nodes = []
    used_words = set()
    for i, (k, b) in enumerate(sorted(shapes, key=lambda s: (round(s[1][1] / 4), s[1][0]))):
        ws = _words_in(words, b, 1)
        used_words.update(id(w) for w in ws)
        nodes.append(
            {"id": f"n{i}", "label": _label_of(ws), "shape": k, "bbox": [round(x, 1) for x in b]}
        )
    edge_labels = []
    for b in small_rects:
        ws = _words_in(words, b, 1)
        if ws:
            edge_labels.append((_center(b), _label_of(ws)))
            used_words.update(id(w) for w in ws)

    # 連結線：直線と塗りなしの折れ線。矢じりのある端が終点
    paths = []
    for ln in segs:
        paths.append(
            [(float(ln["x0"]), float(ln["top"])), (float(ln["x1"]), float(ln["bottom"]))]
            if ln.get("pts") is None
            else _pts(ln)
        )
    for c in curves:
        if not c.get("fill") and not _is_arrowhead(c):
            paths.append(_pts(c))
    head_pts = [_center([h["x0"], h["top"], h["x1"], h["bottom"]]) for h in heads]

    def node_at(p, exclude=None):
        best, bd = None, 1e9
        for n in nodes:
            if n["id"] == exclude:
                continue
            b = n["bbox"]
            dx = max(b[0] - p[0], 0, p[0] - b[2])
            dy = max(b[1] - p[1], 0, p[1] - b[3])
            d = math.hypot(dx, dy)
            if d < bd:
                best, bd = n["id"], d
        return best if bd <= 12 else None

    edges = []
    for pts in paths:
        if len(pts) < 2:
            continue
        a, z = pts[0], pts[-1]
        da = min((math.hypot(a[0] - h[0], a[1] - h[1]) for h in head_pts), default=99)
        dz = min((math.hypot(z[0] - h[0], z[1] - h[1]) for h in head_pts), default=99)
        if da < dz:
            a, z, pts = z, a, list(reversed(pts))
        src, dst = node_at(a), node_at(z)
        if src is None or dst is None or src == dst:
            continue
        lab, ld = None, 18.0
        for c, t in edge_labels:
            d = min(_dist_pt_seg(c, pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            d += 0.25 * math.hypot(c[0] - a[0], c[1] - a[1])
            if d < ld:
                lab, ld = t, d
        edges.append({"from": src, "to": dst, "label": lab})
    # 重複辺を除く
    seen, uniq_e = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["label"])
        if k not in seen:
            seen.add(k)
            uniq_e.append(e)
    if not uniq_e:
        return None
    has_decision = any(n["shape"] == "decision" for n in nodes) or any(e["label"] for e in uniq_e)
    return {"kind": "flowchart" if has_decision else "steps", "nodes": nodes, "edges": uniq_e}


def read_matrix(table) -> dict | None:
    rows = [[compact(c or "") for c in r] for r in table.extract()]
    if len(rows) < 2 or len(rows[0]) < 2:
        return None
    body = [r[1:] for r in rows[1:]]
    cells = [c for r in body for c in r]
    if not cells or not all(c and set(c) <= MARKS for c in cells):
        return None
    return {"kind": "matrix", "rows": [r[0] for r in rows[1:]], "cols": rows[0][1:], "marks": body}


def read_timeline(g: PageGraphics, box) -> dict | None:
    segs = [
        ln
        for ln in g.lines
        if _inside(_center([ln["x0"], ln["top"], ln["x1"], ln["bottom"]]), box, 2)
    ]
    horiz = [
        s
        for s in segs
        if abs(s["top"] - s["bottom"]) < 1 and s["x1"] - s["x0"] > 0.5 * (box[2] - box[0])
    ]
    if not horiz:
        return None
    axis = max(horiz, key=lambda s: s["x1"] - s["x0"])
    ay = axis["top"]
    words = _words_in(g.words, box, 2)
    ticks = sorted([w for w in words if w["top"] > ay], key=lambda w: w["x0"])
    if len(ticks) < 2:
        return None
    tick_x = [(_center([w["x0"], w["top"], w["x1"], w["bottom"]])[0], w["text"]) for w in ticks]
    bars = [
        c
        for c in g.curves
        if c.get("fill")
        and _inside(_center([c["x0"], c["top"], c["x1"], c["bottom"]]), box, 2)
        and c["bottom"] < ay
        and c["x1"] - c["x0"] > 15
    ]

    def tick_near(x):
        return min(tick_x, key=lambda t: abs(t[0] - x))[1]

    lanes = sorted({round(c["top"]) for c in bars})
    spans, events = [], []
    for c in sorted(bars, key=lambda c: (c["top"], c["x0"])):
        b = [c["x0"], c["top"], c["x1"], c["bottom"]]
        ws = [
            w
            for w in words
            if w["bottom"] < ay
            and _inside(_center([w["x0"], w["top"], w["x1"], w["bottom"]]), b, 3)
        ]
        lab = _label_of(ws)
        # 旗（短い塗り形で、目盛より上の最上段）＝出来事
        if c["x1"] - c["x0"] < 40 and round(c["top"]) == lanes[0] and len(lanes) > 1:
            events.append({"at": tick_near(c["x0"]), "label": lab})
        else:
            spans.append(
                {
                    "from": tick_near(c["x0"]),
                    "to": tick_near(c["x1"]),
                    "label": lab,
                    "lane": lanes.index(round(c["top"])),
                }
            )
    if not spans:
        return None
    return {
        "kind": "timeline",
        "axis": {"ticks": [t for _, t in tick_x]},
        "spans": spans,
        "events": events,
    }


def figure_facts(dg: dict, legend: dict[str, str] | None = None) -> list[str]:
    """図の説明文（印刷された図の構造から機械的に作る）。"""
    k = dg.get("kind")
    out = []
    if k in ("flowchart", "steps"):
        lab = {n["id"]: n["label"] for n in dg["nodes"]}
        for e in dg["edges"]:
            if e.get("label"):
                out.append(
                    f"「{lab[e['from']]}」が「{e['label']}」の場合は「{lab[e['to']]}」に進む。"
                )
            else:
                out.append(f"「{lab[e['from']]}」から「{lab[e['to']]}」に進む。")
        # 端点への経路（分岐のラベルの並び）
        succ = defaultdict(list)
        for e in dg["edges"]:
            succ[e["from"]].append(e)
        indeg = {n["id"]: 0 for n in dg["nodes"]}
        for e in dg["edges"]:
            indeg[e["to"]] += 1
        starts = [n for n, d in indeg.items() if d == 0]
        sinks = [n["id"] for n in dg["nodes"] if not succ[n["id"]]]
        paths: dict[str, list[list[str]]] = defaultdict(list)

        def walk(n, labs, seen):
            if len(paths) > 50 or len(seen) > 30:
                return
            if not succ[n]:
                paths[n].append(labs)
                return
            for e in succ[n]:
                if e["to"] not in seen:
                    walk(e["to"], labs + ([e["label"]] if e.get("label") else []), seen | {e["to"]})

        for s in starts:
            walk(s, [], {s})
        for t in sinks:
            ps = paths.get(t) or []
            if len(ps) == 1 and ps[0]:
                out.append(
                    f"「{lab[t]}」に進むのは、判定が順に"
                    + "、".join(f"「{x}」" for x in ps[0])
                    + "となる場合だけである。"
                )
    elif k == "matrix":
        for i, r in enumerate(dg["rows"]):
            for j, c in enumerate(dg["cols"]):
                m = dg["marks"][i][j]
                mean = (legend or {}).get(m, m)
                out.append(f"「{r}」で「{c}」のときは{mean}。")
    elif k == "timeline":
        for s in dg["spans"]:
            out.append(
                f"「{s['label']}」の区間は{s['from']}から{s['to']}まで（{s['lane'] + 1}段目）。"
            )
        for e in dg["events"]:
            out.append(f"「{e['label']}」は{e['at']}の時点。")
    return out


# ---------------------------------------------------------------- 組み立て


class Builder:
    def __init__(self, pdf_id: str):
        self.pdf_id = pdf_id
        self.vals = Values()
        self.n = defaultdict(int)
        self.body: list[dict] = []
        self.front: list[dict] = []
        self.labels: dict[str, dict] = {}
        self.stack: dict[str, dict | None] = {
            "part": None,
            "chapter": None,
            "section": None,
            "article": None,
            "appx": None,
            "appxsec": None,
            "rider": None,
        }
        self.para: dict | None = None
        self.item: dict | None = None
        self.fn_block: dict | None = None
        self.fn_item: dict | None = None
        self.stats = defaultdict(int)

    def nid(self, prefix: str) -> str:
        self.n[prefix] += 1
        return f"{prefix}{self.n[prefix]}"

    # 引用パス
    def path(self) -> list[dict]:
        order = ["part", "chapter", "section", "rider", "appx", "appxsec", "article"]
        return [self.stack[k] for k in order if self.stack[k]]

    def _label(self, node: dict):
        cites = [x["label"] or x.get("title", "") for x in self.path() if x is not node] + [
            node["label"] or node.get("title", "")
        ]
        if node["kind"] in ("paragraph", "item"):
            cites = [x["label"] or x.get("title", "") for x in self.path()]
            if node["kind"] == "item" and self.para:
                cites.append(self.para["label"])
            cites.append(node["label"])
        self.labels[node["id"]] = {
            "citation": " ".join(c for c in cites if c),
            "kind": node["kind"],
        }

    def _attach_container(self, node: dict, level: str):
        """見出しノードを木に付ける。"""
        parent = None
        if level == "part":
            parent = None
        elif level in ("chapter", "rider", "appx"):
            parent = self.stack["part"] if level == "chapter" else None
        elif level == "section":
            parent = self.stack["chapter"]
        elif level == "appxsec":
            parent = self.stack["appx"]
        elif level == "article":
            parent = (
                self.stack["appxsec"]
                or self.stack["appx"]
                or self.stack["section"]
                or self.stack["chapter"]
                or self.stack["rider"]
                or self.stack["part"]
            )
        (parent["children"] if parent else self.body).append(node)

    def heading(self, level: str, label: str, title: str, src: dict):
        kind = {
            "part": "part",
            "chapter": "chapter",
            "section": "section",
            "article": "article",
            "appx": "appendix",
            "appxsec": "appendix_section",
            "rider": "rider",
        }[level]
        prefix = {
            "part": "pt",
            "chapter": "ch",
            "section": "s",
            "article": "a",
            "appx": "x",
            "appxsec": "xs",
            "rider": "r",
        }[level]
        node = {
            "id": self.nid(prefix),
            "kind": kind,
            "label": label,
            "title": self.vals.sub(title, prefix),
            "children": [],
            "blocks": [],
            "src": [src],
        }
        resets = {
            "part": ["part", "chapter", "section", "article", "appx", "appxsec", "rider"],
            "chapter": ["chapter", "section", "article", "appx", "appxsec", "rider"],
            "rider": ["chapter", "section", "article", "appx", "appxsec", "rider"],
            "appx": ["chapter", "section", "article", "appx", "appxsec", "rider"],
            "section": ["section", "article", "appxsec"],
            "appxsec": ["appxsec", "article"],
            "article": ["article"],
        }[level]
        for k in resets:
            self.stack[k] = None
        self._attach_container(node, level)
        self.stack[level] = node
        self._label(node)
        self.para = self.item = None
        self.fn_block = self.fn_item = None
        self.stats[f"head_{kind}"] += 1
        return node

    def last_para_num(self) -> int:
        """今の条で最後に読めた項の番号（番号の無い最初の項は 1）。"""
        art = self.stack["article"]
        nums = [1]
        for c in art["children"] if art else []:
            lab = (c.get("label") or "").translate(_Z2H_DIGIT)
            if c.get("kind") == "paragraph" and lab.isdigit():
                nums.append(int(lab))
        return max(nums)

    def n_para_in_article(self) -> int:
        """今の条の段落の数（項の番号の連番の判定に使う。条の最初の無番号の段落は 1 項に当たる）。"""
        art = self.stack["article"]
        return sum(1 for c in art["children"] if c.get("kind") == "paragraph") if art else 0

    def owner(self) -> dict | None:
        return (
            self.stack["article"]
            or self.stack["appxsec"]
            or self.stack["appx"]
            or self.stack["section"]
            or self.stack["chapter"]
            or self.stack["rider"]
            or self.stack["part"]
        )

    def start_para(self, label: str, text: str, src: dict, x_first: float):
        own = self.owner()
        fam = _label_family(label)
        if own is None:
            node = {
                "id": self.nid("f"),
                "kind": "paragraph",
                "label": label,
                "text": "",
                "raw": [text],
                "children": [],
                "blocks": [],
                "src": [src],
                "x_first": x_first,
                "fam": fam,
            }
            self.front.append(node)
            self.para, self.item = node, None
            return
        if (
            self.para is not None
            and fam
            and self.para.get("fam")
            and fam != self.para["fam"]
            and self.para["fam"] != "none"
            and self.para in own["children"]
        ):
            node = {
                "id": self.nid("i"),
                "kind": "item",
                "label": label,
                "text": "",
                "raw": [text],
                "children": [],
                "blocks": [],
                "src": [src],
                "x_first": x_first,
                "fam": fam,
            }
            self.para["children"].append(node)
            self.item = node
            self._label(node)
            self.stats["item"] += 1
            return
        node = {
            "id": self.nid("p"),
            "kind": "paragraph",
            "label": label,
            "text": "",
            "raw": [text],
            "children": [],
            "blocks": [],
            "src": [src],
            "x_first": x_first,
            "fam": fam or "none",
        }
        own["children"].append(node)
        self.para, self.item = node, None
        self._label(node)
        self.stats["paragraph"] += 1

    def cont(self, text: str, src: dict):
        u = self.item or self.para
        if u is None:
            self.start_para("", text, src, src["bbox"][0])
            return
        u["raw"].append(text)
        u["src"].append(src)

    def add_block(self, b: dict):
        u = self.item or self.para
        own = self.owner()
        if u is not None and (
            own is None or u in own["children"] or (self.para and u in self.para["children"])
        ):
            u["blocks"].append(b)
        elif own is not None:
            own["blocks"].append(b)
        else:
            self.front.append(b)
        self.stats[f"block_{b['type']}"] += 1

    def footnote(self, text: str, src: dict):
        own = self.owner()
        if self.fn_block is None or self.fn_block.get("_owner") is not own:
            self.fn_block = {
                "type": "footnotes",
                "id": self.nid("fn"),
                "notes": [],
                "src": [],
                "_owner": own,
            }
            (own["blocks"] if own else self.front).append(self.fn_block)
            self.stats["block_footnotes"] += 1
        m = re.match(r"^[（(][*＊※注]\s*([0-9０-９]+)[）)]", text)
        m2 = re.match(r"^([❶-❿])", text)
        if m:
            n = int(nfkc(m.group(1)))
        elif m2:
            n, m = ord(m2.group(1)) - ord("❶") + 1, m2
        else:
            n = len(self.fn_block["notes"]) + 1
        self.fn_item = {"n": n, "raw": [text[m.end() :] if m else text], "src": [src]}
        self.fn_block["notes"].append(self.fn_item)
        self.fn_block["src"].append(src)

    def fn_cont(self, text: str, src: dict):
        self.fn_item["raw"].append(text)
        self.fn_item["src"].append(src)
        self.fn_block["src"].append(src)

    def finish(self) -> None:
        def fin(o):
            if isinstance(o, dict):
                if "raw" in o and o.get("kind") in ("paragraph", "item"):
                    o["text"] = self.vals.sub(_cjk_join(o.pop("raw")), o["id"])
                    o.pop("x_first", None)
                    o.pop("fam", None)
                if o.get("type") == "footnotes":
                    o.pop("_owner", None)
                    for it in o["notes"]:
                        it["text"] = self.vals.sub(_cjk_join(it.pop("raw")), o["id"])
                for k in ("children", "blocks"):
                    for c in o.get(k) or []:
                        fin(c)

        for x in self.body + self.front:
            fin(x)


def _label_family(label: str) -> str:
    s = nfkc(label)
    if not s:
        return ""
    if re.match(r"^\(\d+\)$", s):
        return "paren"
    if re.match(r"^\d+\.$", s):
        return "dot"
    if re.match(r"^[①-⑳]$", label):
        return "circle"
    return "other"


def _toc_pages(lines: list[Line]) -> set[int]:
    by: dict[int, list[Line]] = defaultdict(list)
    for ln in lines:
        by[ln.page].append(ln)
    out = set()
    for p, ls in by.items():
        if not ls:
            continue
        digit_only = sum(1 for ln in ls if re.fullmatch(r"[0-9０-９]{1,3}", ln.text.strip()))
        tail = sum(
            1
            for ln in ls
            if RE_TOC_TAIL.search(ln.text.strip()) and "。" not in ln.text and len(ln.text) > 4
        )
        if (digit_only + tail) / len(ls) >= 0.3 and p <= max(4, len(by) // 4):
            out.add(p)
    return out


def build(pdf_id: str, pdf_path: Path) -> dict:
    """PDF（pdf_path）から pdoc を作る。pdf_id は出力に付ける識別子。"""
    lines, page_list = extract_geometry(pdf_path, pdf_id)
    pages = {p.page: p for p in page_list}
    # 契約書の体裁（印字形から判定。約款では None）。契約書だけの規則（項の番号・様式型の見出し）に使う
    scheme = detect_contract_scheme([ln.text.strip() for ln in lines])
    contract_errors: list[dict] = []
    furn = detect_furniture(page_list, lines)
    sizes = [ln.size for ln in lines if ln.size]
    body_size = statistics.mode(round(s * 2) / 2 for s in sizes) if sizes else 9.5
    toc = _toc_pages(lines)
    B = Builder(pdf_id)

    # 柱の判定から、本文の大きさ以上の太字の見出し行を戻す（章題が柱にも出るため）
    def heading_like(ln: Line) -> bool:
        t = compact(ln.text)
        return (
            is_bold(ln)
            and (ln.size or 0) >= body_size - 0.05
            and bool(
                RE_PART.match(t)
                or RE_CHAP.match(t)
                or RE_SEC.match(t)
                or RE_ART.match(t)
                or RE_APPX.match(t)
                or RE_RIDER.search(t)
            )
        )

    furn = {
        k
        for k in furn
        if not any(
            ln.page == k[0]
            and ln.line_no == k[1]
            and heading_like(ln)
            and ln.y0 > pages[ln.page].height * 0.045
            for ln in lines
        )
    }

    pdf = pdfplumber.open(str(pdf_path))
    regions: dict[int, list[dict]] = defaultdict(list)  # page → [{kind, bbox, ...}]
    graphics: dict[int, PageGraphics] = {}
    for pno in sorted({ln.page for ln in lines}):
        if pno in toc:
            continue
        g = PageGraphics(pdf.pages[pno - 1])
        graphics[pno] = g
        for t in g.tables:
            mx = read_matrix(t)
            cells = [c for row in t.extract() for c in row]
            empty = sum(1 for c in cells if not (c or "").strip())
            degenerate = bool(cells) and empty / len(cells) >= 0.4
            regions[pno].append(
                {
                    "kind": "matrix" if mx else "table",
                    "bbox": list(t.bbox),
                    "table": t,
                    "matrix": mx,
                    "degenerate": degenerate and not mx,
                }
            )
        tb = [
            r["bbox"]
            for r in regions[pno]
            if r["kind"] in ("table", "matrix") and not r.get("degenerate")
        ]
        for fb in g.formula_groups(tb):
            regions[pno].append({"kind": "formula", "bbox": fb})
        fm = [r["bbox"] for r in regions[pno] if r["kind"] == "formula"]
        boxes = g.light_boxes()
        boxes += [b for b in g.framed_boxes(tb + fm) if not any(_overlap(b, o) for o in boxes)]
        for b in boxes:
            if any(
                _overlap(b, r["bbox"])
                and r["kind"] in ("table", "matrix")
                and not r.get("degenerate")
                and _inside(_center(b), r["bbox"])
                for r in regions[pno]
            ):
                continue
            if any(_inside(_center(b), f) for f in fm):
                continue
            regions[pno].append({"kind": "box", "bbox": b})

    # 図：図のキャプション行の上（同じ段）にある、表・囲みに属さない描画要素の塊
    def fig_region(ln: Line):
        g = graphics.get(ln.page)
        if g is None:
            return None
        cx = (ln.x0 + ln.x1) / 2
        gut = pages[ln.page].gutter
        if gut and pages[ln.page].n_cols == 2 and ln.x1 - ln.x0 < (pages[ln.page].width * 0.5):
            colx = (0, gut) if cx < gut else (gut, pages[ln.page].width)
        else:
            colx = (0, pages[ln.page].width)
        objs = []
        for o in g.curves + g.lines + g.rects:
            b = [o["x0"], o["top"], o["x1"], o["bottom"]]
            if (
                b[3] <= ln.y0 + 1
                and b[1] >= ln.y0 - 420
                and colx[0] - 2 <= b[0]
                and b[2] <= colx[1] + 2
            ):
                if any(
                    r["kind"] in ("table", "box", "formula", "matrix")
                    and not r.get("degenerate")
                    and _inside(_center(b), r["bbox"])
                    for r in regions[ln.page]
                ):
                    continue
                if b[2] - b[0] > 0.97 * (colx[1] - colx[0]) and b[3] - b[1] < 1.5:
                    continue
                objs.append(b)
        if not objs:
            return None
        # キャプションから上へ、隙間 24pt 以内で連なる塊を取る
        objs.sort(key=lambda b: -b[3])
        top = ln.y0
        chosen = []
        for b in objs:
            if b[3] >= top - 24:
                chosen.append(b)
                top = min(top, b[1])
        if not chosen:
            return None
        u = _union(chosen)
        return [
            u[0],
            u[1],
            max(u[2], min(colx[1], u[2] + 10)),
            ln.y0 - 0.5,
        ]  # 目盛の語はキャプションの直上まで

    for ln in lines:
        if ln.page in toc or (ln.page, ln.line_no) in furn:
            continue
        if RE_FIGCAP.match(compact(ln.text)) and ln.size and ln.size <= body_size:
            if any(
                r["kind"] == "matrix"
                and r["bbox"][3] - 5 <= ln.y0 <= r["bbox"][3] + 60
                and r["bbox"][0] - 10 <= ln.x0 <= r["bbox"][2]
                for r in regions[ln.page]
            ):
                continue
            fb = fig_region(ln)
            if fb:
                regions[ln.page].append(
                    {"kind": "figure", "bbox": fb, "caption_line": (ln.page, ln.line_no)}
                )

    # 見出しの帯（章題などを塗りの帯に載せたもの）は囲みではない
    for pno, rs in regions.items():
        keep = []
        for r in rs:
            if r["kind"] == "box":
                inl = sorted(
                    [
                        ln
                        for ln in lines
                        if ln.page == pno and _inside(_center(_line_box(ln)), r["bbox"], 1.0)
                    ],
                    key=lambda ln: (ln.y0, ln.x0),
                )
                if not inl or (heading_like(inl[0]) and len(inl) <= 2):
                    continue
            keep.append(r)
        regions[pno] = keep

    # 図の領域の中の表（目盛や区間の罫を表と誤検出したもの）は捨てる。退化した表（空のセルが多い）も捨てる
    for pno, rs in regions.items():
        figs = [r["bbox"] for r in rs if r["kind"] == "figure"]
        keep = []
        for r in rs:
            if r["kind"] in ("table", "box", "formula") and any(
                _inside(_center(r["bbox"]), f, 1) for f in figs
            ):
                B_drop = True
            else:
                B_drop = r["kind"] == "table" and r.get("degenerate")
            if not B_drop:
                keep.append(r)
        regions[pno] = keep

    def region_of(ln: Line):
        c = _center(_line_box(ln))
        best = None
        for r in regions.get(ln.page, []):
            if _inside(c, r["bbox"], 1.0) and (
                best is None
                or (r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1])
                < (best["bbox"][2] - best["bbox"][0]) * (best["bbox"][3] - best["bbox"][1])
            ):
                best = r
        return best

    def src_of(ln: Line) -> dict:
        return {"page": ln.page, "line": ln.line_no, "bbox": [round(x, 1) for x in _line_box(ln)]}

    emitted: set[int] = set()
    pending_table_caption: tuple[str, dict] | None = None
    last_table: dict | None = None
    started = False
    # 段落の字下げの基準（ページ・段ごとの左端）
    col_left: dict[tuple[int, int], float] = {}
    for ln in lines:
        key = (ln.page, 0 if not pages[ln.page].gutter or ln.x0 < pages[ln.page].gutter else 1)
        col_left[key] = min(col_left.get(key, 1e9), ln.x0)

    def rel_x(ln: Line) -> float:
        key = (ln.page, 0 if not pages[ln.page].gutter or ln.x0 < pages[ln.page].gutter else 1)
        return ln.x0 - col_left[key]

    cw_all = [ln.char_w for ln in lines if ln.char_w and abs((ln.size or 0) - body_size) < 0.3]
    cw = statistics.median(cw_all) if cw_all else body_size
    prev_body: Line | None = None
    in_fn = False
    pending_title: tuple[str, dict] | None = None

    for ln in lines:
        if ln.page in toc or (ln.page, ln.line_no) in furn:
            continue
        text = ln.text.strip()
        t = compact(text)
        if not t:
            continue
        # 契約書の様式型の章（「1用語の意味」）は薄い塗りの帯の上に印字されるので、囲みの領域より先に見出しにする
        if (
            scheme
            and is_bold(ln)
            and (ln.size or 0) > body_size + 0.4
            and (mfc0 := RE_FORM_CHAP.match(t))
        ):
            started = True
            B.heading("chapter", mfc0.group(1), mfc0.group(2), src_of(ln))
            prev_body, in_fn = None, False
            continue
        r = region_of(ln)
        if r is not None:
            rid = id(r)
            if rid in emitted:
                continue
            emitted.add(rid)
            blk = _region_block(B, r, ln, lines, graphics, pending_table_caption, src_of)
            pending_table_caption = None
            if blk is None:
                continue
            if blk["type"] == "table" and last_table is not None and _same_header(last_table, blk):
                last_table["grid"] += blk["grid"][1:]
                last_table["src"] += blk["src"]
                B.stats["table_merged"] += 1
                continue
            B.add_block(blk)
            last_table = blk if blk["type"] == "table" else None
            prev_body, in_fn = None, False
            continue
        bold = is_bold(ln)
        big = (ln.size or 0) >= body_size - 0.05
        # 表・図のキャプション（次の表・図に付ける）
        if RE_TABCAP.match(t) and (ln.size or 0) <= body_size:
            pending_table_caption = (re.sub(rf"^表{_D}\s*", "", text), src_of(ln))
            continue
        if RE_FIGCAP.match(t) and (ln.size or 0) <= body_size:
            continue  # 図の領域が取れなかったキャプション（図の本体は無い）
        if bold and big and re.fullmatch(r"[（(][^（）()]{1,40}[）)]", t):
            pending_title = (text, src_of(ln))
            continue
        mrun = re.match(rf"^第{_D}条(の{_D})?", nfkc(text).replace(" ", ""))
        if mrun is None and scheme == KANJI:
            # 漢数字の条番号の契約書（「（総則）」の次の行が「第一条甲および乙は…」）。
            # 題名の行の直後に限るので、本文中の「第三条に定める」は条にならない
            mrun = re.match(
                rf"^第[{KANJI_NUM}]+条(の[{KANJI_NUM}]+)?(?![にのをでがは])",
                nfkc(text).replace(" ", "").replace("　", ""),
            )
        if pending_title and mrun and not bold:
            raw = text.replace(" ", "").replace("　", "")
            label = raw[: len(mrun.group(0))]
            B.heading("article", label, pending_title[0].strip("（）()"), pending_title[1])
            started = True
            pending_title = None
            B.start_para("", raw[len(mrun.group(0)) :], src_of(ln), rel_x(ln))
            prev_body, in_fn = ln, False
            continue
        if pending_title:  # 次の行が条でなかった題名は本文に戻す
            B.cont(pending_title[0], pending_title[1]) if started else None
            pending_title = None
        if scheme and bold:
            mfc = RE_FORM_CHAP.match(t) if (ln.size or 0) > body_size + 0.4 else None
            mfa = RE_FORM_ART.match(t)
            if mfc or mfa:
                started = True
                lvl = "chapter" if mfc else "article"
                mm = mfc or mfa
                B.heading(lvl, mm.group(1), mm.group(2), src_of(ln))
                prev_body, in_fn = None, False
                continue
        level = None
        if bold and big:
            if RE_PART.match(t):
                level = "part"
            elif RE_CHAP.match(t):
                level = "chapter"
            elif RE_SEC.match(t):
                level = "section"
            elif RE_ART.match(t):
                level = "article"
            elif RE_APPX.match(t):
                level = "appx"
            elif RE_APPXSEC.match(t) and (B.stack["appx"] is not None):
                level = "appxsec"
            elif RE_RIDER.search(t) and (ln.size or 0) > body_size + 0.4 and len(t) <= 40:
                level = "rider"
        if level:
            started = True
            m = {
                "part": RE_PART,
                "chapter": RE_CHAP,
                "section": RE_SEC,
                "article": re.compile(rf"^第{_D}条(の{_D})?"),
                "appx": RE_APPX,
                "appxsec": RE_APPXSEC,
                "rider": None,
            }[level]
            if m is None:
                label, title = "", text
            else:
                mm = m.match(nfkc(text).replace(" ", "").replace("　", ""))
                raw = text.replace(" ", "").replace("　", "")
                label = raw[: len(mm.group(0))]
                title = raw[len(mm.group(0)) :].strip("（）()")
            B.heading(level, label, title, src_of(ln))
            prev_body, in_fn = None, False
            continue
        if not started:
            continue  # 表紙・目次の前置き（本文の見出しが出るまで）
        # 脚注
        small = (ln.size or body_size) < body_size - 0.4
        if RE_FN_HEAD.match(t):
            in_fn = True  # 「第N条　備考」の見出し（次の ❶ から脚注）
            prev_body = ln
            continue
        if RE_FN.match(t) and (small or t[0] in "❶❷❸❹❺❻❼❽❾❿"):
            B.footnote(text, src_of(ln))
            in_fn = True
            prev_body = ln
            continue
        if (
            in_fn
            and B.fn_item is not None
            and small
            and not RE_PLABEL.match(t)
            and not RE_FN.match(t)
        ):
            B.fn_cont(text, src_of(ln))
            prev_body = ln
            continue
        in_fn = False
        m = RE_PLABEL.match(text)
        if scheme and not m and B.stack["article"] is not None and rel_x(ln) <= 0.5 * cw:
            mc = RE_CT_PARA.match(text)
            # 項の番号は条の中で 2 以上・前の項の番号より大きい（前の項が読めなかった場合も拾う）。
            # 行頭が条の参照（「第N条」）や数字の続く語のものは本文として扱う
            if (
                mc
                and 2 <= int(mc.group(1).translate(_Z2H_DIGIT)) <= B.n_para_in_article() + 2
                and int(mc.group(1).translate(_Z2H_DIGIT)) > B.last_para_num()
            ):
                B.start_para(mc.group(1), text[mc.end() :].lstrip("　 "), src_of(ln), rel_x(ln))
                prev_body = ln
                continue
        if m and not (prev_body and RE_ART.match(compact(prev_body.text)) and False):
            label = m.group(0)
            B.start_para(label, text[m.end() :].lstrip("　 "), src_of(ln), rel_x(ln))
        else:
            u = B.item or B.para
            new_par = False
            if u is None or B.owner() is None:
                new_par = u is None
            elif prev_body is not None and prev_body.text.rstrip().endswith("。"):
                prev_full = (
                    prev_body.x1
                    - col_left[
                        (
                            prev_body.page,
                            0
                            if not pages[prev_body.page].gutter
                            or prev_body.x0 < pages[prev_body.page].gutter
                            else 1,
                        )
                    ]
                )
                short = prev_full < 0.85 * max(1.0, _col_width(pages[prev_body.page], prev_body))
                if short and (
                    rel_x(ln) <= 0.5 * cw or (u.get("fam") == "none" and rel_x(ln) >= 0.5 * cw)
                ):
                    new_par = True
            if new_par:
                B.start_para("", text, src_of(ln), rel_x(ln))
            else:
                B.cont(text, src_of(ln))
        prev_body = ln
    B.finish()
    # 読み取りの失敗を隠さない：本文が組めなかった（条も段落も無い）ことを記録する
    if not B.body:
        contract_errors.append(
            {"page": None, "error": "本文の見出し（条など）を 1 つも読めず、本文が空になった"}
        )
    elif B.stats.get("head_article", 0) == 0:
        contract_errors.append({"page": None, "error": "条の見出しを 1 つも読めなかった"})
    n_refs = link_appendix_refs(B.body + B.front)
    B.stats["refs_appendix"] = n_refs
    pdf.close()
    out = {
        "schema_version": SCHEMA,
        "content_id": pdf_id,
        "meta": {"constants": B.vals.constants},
        "front_matter": B.front,
        "defined_terms": [],
        "body": B.body,
        "appendices": [],
        "back_matter": [],
        "derived": {"labels": B.labels, "tables": {}, "figures": {}},
        "pdoc": {
            "pdf_id": pdf_id,
            "scheme": scheme,
            "body_size": body_size,
            "toc_pages": sorted(toc),
            "n_lines": len(lines),
            "n_furniture": len(furn),
            "stats": dict(B.stats),
            "n_value_spans": B.vals.n_spans,
            "n_dates_kept": B.vals.n_dates,
            "n_kanji_values": B.vals.n_kanji,
            "read_errors": [
                {"page": p, "error": e} for p, g in sorted(graphics.items()) for e in g.errors
            ]
            + contract_errors,
            "value_span_errors": B.vals.errors,
        },
    }
    return out


RE_APPX_REF = re.compile(rf"(別表|付表)\s*({_D})")


def link_appendix_refs(roots: list) -> int:
    """本文の「別表N」「付表N」を、その別表のノードへの参照（refs: ["{ref:<id>}"]）として結ぶ。

    PDF では印字された文字列なので、別表の見出しのラベルと照合して決定的に結ぶ。
    """
    appx: dict[str, str] = {}

    def collect(o):
        if isinstance(o, dict):
            if o.get("kind") == "appendix" and o.get("label"):
                m = RE_APPX_REF.match(compact(o["label"]))
                if m:
                    appx.setdefault(m.group(1) + nfkc(m.group(2)), o["id"])
            for k in ("children", "blocks"):
                for c in o.get(k) or []:
                    collect(c)
        elif isinstance(o, list):
            for c in o:
                collect(c)

    n = 0

    def link(o):
        nonlocal n
        if isinstance(o, dict):
            texts = [o.get("text") or ""] + [it.get("text") or "" for it in o.get("notes") or []]
            hits = []
            for t in texts:
                for m in RE_APPX_REF.finditer(compact(t)):
                    tgt = appx.get(m.group(1) + nfkc(m.group(2)))
                    if tgt and tgt != o.get("id") and "{ref:" + tgt + "}" not in hits:
                        hits.append("{ref:" + tgt + "}")
            if hits and o.get("kind") != "appendix":
                o["refs"] = hits
                n += len(hits)
            for k in ("children", "blocks"):
                for c in o.get(k) or []:
                    link(c)
        elif isinstance(o, list):
            for c in o:
                link(c)

    collect(roots)
    link(roots)
    return n


def _col_width(pg, ln: Line) -> float:
    if pg.gutter and pg.n_cols == 2:
        return (pg.gutter - 30) if ln.x0 < pg.gutter else (pg.width - pg.gutter - 30)
    return pg.width - 70


def _same_header(prev: dict, cur: dict) -> bool:
    if prev.get("caption") and cur.get("caption") and prev["caption"] != cur["caption"]:
        return False
    if cur.get("caption"):
        return False
    a = [compact(c["text"]) for c in prev["grid"][0]]
    b = [compact(c["text"]) for c in cur["grid"][0]]
    return a == b and len(a) == len(b)


def _semantic_type(grid: list[list[str]]) -> str:
    head = "".join(grid[0]) if grid else ""
    first_col = [r[0] for r in grid[1:] if r]
    nums = sum(
        1 for r in grid[1:] for c in r[1:] if RE_VALUE.search(c) or re.search(r"[0-9０-９]", c)
    )
    if first_col and sum(
        1 for c in first_col if re.match(r"^[①-⑳]|^[アイウエオカキクケコ]$", c)
    ) >= len(first_col) * tun("pdoc.semtype_frac", 0.6):
        text = "".join(c for r in grid for c in r)
        return "exclusions" if re.search(r"支払いません|支払わない|対象外|除き", text) else "items"
    # 最後の列が支払の可否（「取扱い」の表など）：行ごとの場合分けで支払うかどうかを定める表（TV2.1）
    body = [r for r in grid[1:] if r]
    verdicts = [r[-1] for r in body if RE_PAY_VERDICT.search(r[-1])]
    if body and len(verdicts) >= len(body) * tun("pdoc.semtype_frac", 0.6):
        return "exclusions" if any(RE_PAY_NEG.search(v) for v in verdicts) else "conditions"
    if re.search(r"等級|級", head):
        return "grade_schedule"
    if re.search(r"割合|率|係数|倍率", head):
        return "rate"
    if re.search(r"額|金額|保険金|給付", head) and nums:
        return "benefit_schedule"
    if re.search(r"用語|定義", head):
        return "definitions"
    if nums >= max(2, len(grid) - 1):
        return "rate"
    return "other"


def _region_block(
    B: Builder, r: dict, first_line: Line, lines: list[Line], graphics, caption, src_of
) -> dict | None:
    page = first_line.page
    inside = [
        ln for ln in lines if ln.page == page and _inside(_center(_line_box(ln)), r["bbox"], 1.0)
    ]
    srcs = [src_of(ln) for ln in inside]
    if r["kind"] == "table":
        rows = r["table"].extract()
        grid = [[{"text": _cjk_join((c or "").split("\n"))} for c in row] for row in rows]
        texts = [[c["text"] for c in row] for row in grid]
        blk = {
            "type": "table",
            "id": B.nid("tbl"),
            "caption": caption[0] if caption else "",
            "semantic_type": _semantic_type(texts),
            "grid": grid,
            "src": srcs,
            "bbox": [round(x, 1) for x in r["bbox"]],
            "page": page,
        }
        if caption:
            blk["src"] = [caption[1]] + blk["src"]
        return blk
    if r["kind"] == "matrix":
        dg = r["matrix"]
        legend = {}
        below = [
            ln
            for ln in lines
            if ln.page == page
            and r["bbox"][3] - 1 <= ln.y0 <= r["bbox"][3] + 30
            and r["bbox"][0] - 5 <= ln.x0 <= r["bbox"][2]
        ]
        for ln in below:
            for m, mean in re.findall(r"([○×△◎])[＝=]([^○×△◎\s]+)", ln.text):
                legend[m] = mean
        if legend:
            dg["legend"] = [{"mark": k, "meaning": v} for k, v in legend.items()]
        dg = _spans_in_diagram(B, dg)
        cap = ""
        for ln in lines:
            if (
                ln.page == page
                and RE_FIGCAP.match(compact(ln.text))
                and r["bbox"][3] - 5 <= ln.y0 <= r["bbox"][3] + 60
            ):
                cap = re.sub(rf"^図{_D}\s*", "", ln.text.strip())
                srcs = srcs + [src_of(ln)]
                break
        return {
            "type": "figure",
            "id": B.nid("fig"),
            "caption": cap,
            "diagram": dg,
            "facts": figure_facts(dg, legend),
            "src": srcs,
            "bbox": [round(x, 1) for x in r["bbox"]],
            "page": page,
        }
    if r["kind"] == "box":
        inside.sort(key=lambda ln: (ln.y0, ln.x0))
        title = inside[0].text.strip() if inside and is_bold(inside[0]) else ""
        body_lines = inside[1:] if title else inside
        paras: list[list[str]] = []
        for ln in body_lines:
            if not paras or (
                paras[-1] and paras[-1][-1].endswith("。") and ln.x0 <= body_lines[0].x0 + 1
            ):
                paras.append([])
            paras[-1].append(ln.text.strip())
        texts = [_cjk_join(p) for p in paras if p]
        is_example = any(
            re.search(r"[0-9０-９]", s) and re.search(r"(とき|場合)(は|には)", s) for s in texts
        )
        bid = B.nid("box") + ("_note" if is_example else "")
        blocks = [
            {"type": "paragraph", "id": f"{bid}_p{i + 1}", "text": B.vals.sub(s, bid)}
            for i, s in enumerate(texts)
        ]
        return {
            "type": "box",
            "id": bid,
            "title": title,
            "blocks": blocks,
            "src": srcs,
            "bbox": [round(x, 1) for x in r["bbox"]],
            "page": page,
        }
    if r["kind"] == "formula":
        text = graphics[page].formula_text(r["bbox"])
        return {
            "type": "formula",
            "id": B.nid("fml"),
            "terms": [{"text": B.vals.sub(text, "fml")}],
            "alt": "",
            "src": srcs,
            "bbox": [round(x, 1) for x in r["bbox"]],
            "page": page,
        }
    if r["kind"] == "figure":
        g = graphics[page]
        dg = read_timeline(g, r["bbox"]) or read_flowchart(g, r["bbox"])
        cap_ln = next((ln for ln in lines if (ln.page, ln.line_no) == r["caption_line"]), None)
        cap = re.sub(rf"^図{_D}\s*", "", cap_ln.text.strip()) if cap_ln else ""
        if dg is None:
            words = _words_in(g.words, r["bbox"], 1)
            dg = {
                "kind": "diagram",
                "nodes": [{"id": f"n{i}", "label": _label_of([w])} for i, w in enumerate(words)],
                "edges": [],
            }
        dg = _spans_in_diagram(B, dg)
        srcs = srcs + ([src_of(cap_ln)] if cap_ln else [])
        return {
            "type": "figure",
            "id": B.nid("fig"),
            "caption": cap,
            "diagram": dg,
            "facts": figure_facts(dg),
            "src": srcs,
            "bbox": [round(x, 1) for x in r["bbox"]],
            "page": page,
        }
    return None


def _spans_in_diagram(B: Builder, dg: dict) -> dict:
    for n in dg.get("nodes", []):
        n["label"] = B.vals.sub(n.get("label", ""), "fig")
    for e in dg.get("edges", []):
        if e.get("label"):
            e["label"] = B.vals.sub(e["label"], "fig")
    for s in dg.get("spans", []):
        for k in ("from", "to", "label"):
            s[k] = B.vals.sub(s[k], "fig")
    for e in dg.get("events", []):
        for k in ("at", "label"):
            e[k] = B.vals.sub(e[k], "fig")
    if "axis" in dg:
        dg["axis"]["ticks"] = [B.vals.sub(t, "fig") for t in dg["axis"]["ticks"]]
    if dg.get("kind") == "matrix":
        dg["rows"] = [B.vals.sub(x, "fig") for x in dg["rows"]]
        dg["cols"] = [B.vals.sub(x, "fig") for x in dg["cols"]]
    return dg

"""本文の読み取り精度。

- CER = Levenshtein / gold 長。文字 F1。
- **正規化前と正規化後の両方を報告し、何を正規化したかを記録する**
  （過度な正規化はモデルを実際より良く見せる）。
- 日本語固有の誤り内訳（かな混同・濁点脱落・全半角・丸数字）。
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz.distance import Levenshtein

# --- 正規化の段階。適用したものを必ず記録する ---

NORM_STEPS = ("nfkc", "ws_collapse", "dash_unify", "tilde_unify")

_DASHES = "‐‑‒–—―ー−-"
_TILDES = "〜～"


def normalize(text: str, steps: tuple[str, ...] = NORM_STEPS) -> str:
    out = text
    if "nfkc" in steps:
        out = unicodedata.normalize("NFKC", out)
    if "ws_collapse" in steps:
        out = "".join(out.split())
    if "dash_unify" in steps:
        out = "".join("-" if ch in _DASHES else ch for ch in out)
    if "tilde_unify" in steps:
        out = "".join("~" if ch in _TILDES else ch for ch in out)
    return out


def _strip_ws(text: str) -> str:
    """CER の素の比較でも空白は落とす。日本語では改行位置が意味を持たないため。

    ただしこれは正規化ではなく **比較の前処理** である。NFKC 等とは別に扱い、
    `cer_raw` の定義として明示する。
    """
    return "".join(text.split())


# --- かな混同の対---

CONFUSION_PAIRS = [
    ("ソ", "ン"),
    ("シ", "ツ"),
    ("ロ", "口"),
    ("カ", "力"),
    ("エ", "工"),
    ("ニ", "二"),
    ("ハ", "八"),
    ("ヘ", "△"),
]

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
SPECIAL = "【】〔〕※〇（）"


@dataclass
class TextScore:
    n_pages: int = 0
    cer_raw: float = 0.0
    cer_norm: float = 0.0
    char_f1_raw: float = 0.0
    char_f1_norm: float = 0.0
    cer_worst_decile: float = 0.0
    bag_cer_mean: float = 0.0
    bag_cer_median: float = 0.0
    per_page: list[dict] = field(default_factory=list)
    japanese_breakdown: dict = field(default_factory=dict)
    norm_steps: tuple[str, ...] = NORM_STEPS
    n_missing_pages: int = 0

    def as_metrics(self) -> dict:
        return {
            "cer": round(self.cer_raw, 6),
            "cer_normalized": round(self.cer_norm, 6),
            "char_f1": round(self.char_f1_raw, 6),
            "char_f1_normalized": round(self.char_f1_norm, 6),
            "cer_worst_decile": round(self.cer_worst_decile, 6),
            # **読み順非依存の CER。**読み取りの誤りと読み順の誤りを分けて見るために出す。
            "bag_cer": round(self.bag_cer_mean, 6),
            "bag_cer_median": round(self.bag_cer_median, 6),
            "n_pages_scored": self.n_pages,
            "n_missing_pages": self.n_missing_pages,
            "norm_steps": list(self.norm_steps),
        }


def cer(pred: str, gold: str) -> float:
    """Levenshtein / gold 長。gold が空なら pred も空で 0.0、そうでなければ 1.0。"""
    if not gold:
        return 0.0 if not pred else 1.0
    return Levenshtein.distance(pred, gold) / len(gold)


def bag_cer(pred: str, gold: str) -> float:
    """**読み順に依存しない CER**。

    文字の多重集合の対称差を gold 長で割る。素の CER は 2 段組の読み順が崩れると
    「文字は全部読めているのに大きく出る」ので、**読み取りの誤りと読み順の誤りを
    分離できない**。bag-CER はその分離を与える：

        CER が高く bag-CER が低い   → 読み順（段組）の問題
        両方が高い                  → 文字の読み取りの問題


    **距離は対称差の和ではなく `max` を取る。** 和にすると 1 文字の置換を
    「削除 1 ＋ 挿入 1」で 2 回数えるので、同じ長さの全不一致が 2.0 になり
    **CER（同条件で 1.0）と並べられない。** `max` は置換を 1 と数える
    多重集合上の編集距離であり、CER と同じ尺度になる。
    """
    if not gold:
        return 0.0 if not pred else 1.0
    cp, cg = Counter(pred), Counter(gold)
    ins = sum((cp - cg).values())  # pred にしか無い
    dele = sum((cg - cp).values())  # gold にしか無い
    return max(ins, dele) / len(gold)


def char_f1(pred: str, gold: str) -> float:
    """文字の多重集合 F1（順序を見ない。CER と対にして読む）。"""
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    cp, cg = Counter(pred), Counter(gold)
    overlap = sum((cp & cg).values())
    if overlap == 0:
        return 0.0
    prec = overlap / sum(cp.values())
    rec = overlap / sum(cg.values())
    return 2 * prec * rec / (prec + rec)


def japanese_breakdown(pred: str, gold: str) -> dict:
    """日本語固有の誤りの内訳。**診断用であり、精度指標ではない。**

    出現数の差分を取るだけの粗い指標だが、「どの文字クラスが落ちたか」を示す。
    """
    out: dict = {}

    def cls_count(s: str, chars: str) -> int:
        return sum(s.count(c) for c in chars)

    out["circled_gold"] = cls_count(gold, CIRCLED)
    out["circled_pred"] = cls_count(pred, CIRCLED)
    out["roman_gold"] = cls_count(gold, ROMAN)
    out["roman_pred"] = cls_count(pred, ROMAN)
    out["special_gold"] = cls_count(gold, SPECIAL)
    out["special_pred"] = cls_count(pred, SPECIAL)

    # 濁点・半濁点（結合文字ではなく合成済み文字の数で見る）
    def dakuten(s: str) -> int:
        return sum(
            1
            for ch in s
            if unicodedata.name(ch, "").endswith(("WITH VOICED SOUND MARK",))
            or "SEMI-VOICED" in unicodedata.name(ch, "")
        )

    out["dakuten_gold"] = dakuten(gold)
    out["dakuten_pred"] = dakuten(pred)

    # 全角/半角の傾き
    out["halfwidth_digit_gold"] = sum(c.isdigit() and ord(c) < 128 for c in gold)
    out["halfwidth_digit_pred"] = sum(c.isdigit() and ord(c) < 128 for c in pred)
    out["fullwidth_digit_gold"] = sum("０" <= c <= "９" for c in gold)
    out["fullwidth_digit_pred"] = sum("０" <= c <= "９" for c in pred)

    # かな混同：gold と pred で対の出現数が入れ替わっている量
    conf = {}
    for a, b in CONFUSION_PAIRS:
        da = pred.count(a) - gold.count(a)
        db = pred.count(b) - gold.count(b)
        if da or db:
            conf[f"{a}/{b}"] = [da, db]
    out["confusion_deltas"] = conf
    return out


def score_text(pred_pages: dict[int, str], gold_pages: dict[int, str]) -> TextScore:
    """ページ番号 → 本文 の 2 つの辞書を比較する。

    gold にあって pred に無いページは **欠損として数え、CER 1.0 で採点する**
    （§1.6：空文字で黙って埋めない）。
    """
    s = TextScore()
    agg_pred_raw, agg_gold_raw = [], []
    agg_pred_norm, agg_gold_norm = [], []
    cers: list[float] = []
    bags: list[float] = []

    for num in sorted(gold_pages):
        g = gold_pages[num]
        p = pred_pages.get(num)
        missing = p is None
        if missing:
            s.n_missing_pages += 1
            p = ""

        gr, pr = _strip_ws(g), _strip_ws(p)
        gn, pn = normalize(g), normalize(p)

        c_raw = cer(pr, gr)
        c_norm = cer(pn, gn)
        c_bag = bag_cer(pr, gr)
        cers.append(c_raw)
        bags.append(c_bag)
        s.per_page.append(
            {
                "page": num,
                "cer": round(c_raw, 6),
                "cer_normalized": round(c_norm, 6),
                "bag_cer": round(c_bag, 6),
                "char_f1": round(char_f1(pr, gr), 6),
                "gold_chars": len(gr),
                "pred_chars": len(pr),
                "missing": missing,
            }
        )
        agg_pred_raw.append(pr)
        agg_gold_raw.append(gr)
        agg_pred_norm.append(pn)
        agg_gold_norm.append(gn)
        s.n_pages += 1

    # 集約はページ平均（文書ごとの長さ差で偏らないように）
    if s.n_pages:
        s.cer_raw = sum(x["cer"] for x in s.per_page) / s.n_pages
        s.cer_norm = sum(x["cer_normalized"] for x in s.per_page) / s.n_pages
        s.char_f1_raw = sum(x["char_f1"] for x in s.per_page) / s.n_pages
        s.char_f1_norm = char_f1("".join(agg_pred_norm), "".join(agg_gold_norm))
        # 最悪 10%（法務文書のリーダーが壊れるのは裾）
        k = max(1, round(s.n_pages * 0.1))
        s.cer_worst_decile = sum(sorted(cers, reverse=True)[:k]) / k
        s.bag_cer_mean = sum(bags) / len(bags)
        # **中央値も出す。**少数のページの大きな誤りに平均が引きずられるため。
        sb = sorted(bags)
        s.bag_cer_median = (
            sb[len(sb) // 2] if len(sb) % 2 else (sb[len(sb) // 2 - 1] + sb[len(sb) // 2]) / 2
        )

    s.japanese_breakdown = japanese_breakdown("".join(agg_pred_raw), "".join(agg_gold_raw))
    return s

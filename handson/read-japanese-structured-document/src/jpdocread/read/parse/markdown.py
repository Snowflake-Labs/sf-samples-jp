"""LAYOUT モード出力の Markdown 除去（S1 で必要性が判明）。

**なぜ必要か。** `AI_PARSE_DOCUMENT` の LAYOUT モードは Markdown を返す
（見出し `#`、表の `|` と罫線 `---`）。これを平文の gold と直接 CER 比較すると、
**構造を運んでいることを理由にモデルを罰する**ことになる。

実測（S1・`auto-0001` p5-p7）：除去前 CER 0.0594 → 除去後 **0.0245**（2.4 倍改善）。
除去しないと「LAYOUT はローカル抽出（R4: 0.0670）をほぼ上回らない」という
**誤った結論**に至る。実際には約 2.7 倍良い。

**重要：除去するのは採点の比較時だけ。** Markdown の見出し記号と表のパイプは
P5（構造組立）と P3（表）にとって価値ある特徴量なので、**生の出力は必ず保持する**。
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^#{1,6}\s*", re.M)
_TABLE_RULE = re.compile(r"^\s*\|?\s*[-:\s|]{3,}\s*\|?\s*$", re.M)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_BR = re.compile(r"<br\s*/?>", re.I)


def strip_markdown(text: str) -> str:
    """LAYOUT 出力から Markdown 記法だけを落とし、本文文字を保持する。"""
    t = text
    t = _IMG.sub("", t)
    t = _HTML_BR.sub("\n", t)
    t = _HEADING.sub("", t)
    t = _TABLE_RULE.sub("", t)
    t = _BOLD.sub(r"\1", t)
    t = _ITALIC.sub(r"\1", t)
    t = t.replace("|", " ")
    return t


def has_markdown(text: str) -> bool:
    """LAYOUT 出力かどうかの粗い判定（OCR 出力に誤って適用しないための番犬）。"""
    return bool(_HEADING.search(text) or "|" in text)


# --- 全角/半角の揺れの計測（採点ではなく診断用）---

FULLWIDTH_PARENS = "（）"
HALFWIDTH_PARENS = "()"


def paren_width_shift(pred: str, gold: str) -> dict:
    """全角括弧が半角に変換された量を測る。

    **約款では `（1）` と `(1)` の差が条項の同定に直結する**。
    実測（S1）：LAYOUT モードは gold の全角括弧 21 個のうち 6 個を半角に変換した
    （`（` 21→15、`(` が 6 個増加）。これは「記号を落とした」のではなく
    **静かに正規化している**。引用同一性を壊すので必ず計測して報告する。
    """
    return {
        "fullwidth_gold": sum(gold.count(c) for c in FULLWIDTH_PARENS),
        "fullwidth_pred": sum(pred.count(c) for c in FULLWIDTH_PARENS),
        "halfwidth_gold": sum(gold.count(c) for c in HALFWIDTH_PARENS),
        "halfwidth_pred": sum(pred.count(c) for c in HALFWIDTH_PARENS),
    }

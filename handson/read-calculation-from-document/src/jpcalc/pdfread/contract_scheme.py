"""契約書の体裁の判定（印字形だけから。正解を見ない）。

幾何の段階で、契約書の段組の補正を使うかどうかを決めるために使う。
handson/read-japanese-structured-document の structure/contract.py の detect_contract_scheme と同じ判定で、
判定に要る正規表現だけを切り出した（構造の読み取りの部品は持ち込まない）。
"""

from __future__ import annotations

import re

DIGITS = "0-9０-９"
KANJI_NUM = "一二三四五六七八九十百〇"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

STANDARD, KANJI, FORM = "contract-standard", "contract-kanji", "contract-form"

RE_ART_STD = re.compile(rf"^第([{DIGITS}]+)条(?:の([{DIGITS}]+))?[（(]")
RE_ART_KANJI = re.compile(rf"^第([{KANJI_NUM}]+)条(\S.*)$")
RE_PARTY_DECL = re.compile(r"以下「[^」]{1,10}」という")
# 冒頭の当事者欄（`委託者株式会社…`・`事業主有限会社…`）。役割名は一般的な契約の語彙
PARTY_ROLES = (
    "委託者",
    "受託者",
    "発注者",
    "受注者",
    "注文者",
    "請負者",
    "事業主",
    "労働者",
    "貸主",
    "借主",
    "賃貸人",
    "賃借人",
    "許諾者",
    "実施権者",
    "使用権者",
    "委任者",
    "受任者",
    "開示者",
    "受領者",
    "売主",
    "買主",
    "甲",
    "乙",
    "丙",
    "保証人",
    "家賃債務保証業者",
)
RE_PARTY_FIELD = re.compile(rf"^(?:{'|'.join(sorted(PARTY_ROLES, key=len, reverse=True))})[　 ]*\S")
RE_CIRCLED_LINE = re.compile(rf"^[{CIRCLED}]\S")


def detect_contract_scheme(lines: list[str]) -> str | None:
    """印字形から契約書の体裁を推定する。契約書でなければ None。

    契約書であることの手掛かりは、当事者の呼称の宣言（`以下「甲」という`）が冒頭近くにあるか、
    冒頭の 12 行に当事者欄（`事業主…`・`労働者…`）が 2 つ以上あること（宣言の無い様式型がある）。
    約款は当事者を宣言しない（「保険契約者」等は用語の定義表で定める）。
    """
    head = [s.strip() for s in lines[:80]]
    n_fields = sum(1 for s in head[:12] if RE_PARTY_FIELD.match(s))
    if not any(RE_PARTY_DECL.search(s) for s in head) and n_fields < 2:
        return None
    n_kanji = sum(1 for s in lines if RE_ART_KANJI.match(s.strip()))
    n_std = sum(1 for s in lines if RE_ART_STD.match(s.strip()))
    n_circ = sum(1 for s in lines if RE_CIRCLED_LINE.match(s.strip()))
    if n_kanji >= 3 and n_kanji > n_std:
        return KANJI
    if n_std >= 2:
        return STANDARD
    if n_circ >= 3:
        return FORM
    return None

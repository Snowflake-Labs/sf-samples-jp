"""版式推定と体裁別の見出し文法（T11/T12）。

**なぜ必要か。** `jyusetsu`（重要事項説明書）は約款ではない。`第N章`/`第N条` を
使わず番号だけで階層を作るので、約款用の正規表現は**1 件も当たらない**
（実測：見出し候補 0 件、条 recall 0.000）。大域デコードも候補が無ければ働かない。
文法そのものを差し替える以外に道がない。

**約款の文法は本モジュールに移していない。** `tree.py` の約款経路は
枝番（`第3条の2`）・附則・別表・特約の番号リセットといった**パターンでは書けない
論理**を持っており、YAML に写すと「設定で駆動しているふり」になる。
設定に置くのは本当にデータで決まるもの（jyusetsu のパターンと推定閾値）だけにする。

**版式は印字形から推定する。** gold の `meta.numbering_scheme` は予測時に使えない
（予測側は正解を読まない）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from ...common.paths import CONFIGS

YAKKAN = "yakkan"
JYUSETSU = "jyusetsu"

# 約款らしさの指標：本文中の `第N条`。参照でも見出しでも構わない。
# **ここでは「この体裁が条を使うか」だけを見ている**ので、参照除外は不要。
RE_ARTICLE_KANJI = re.compile(r"第[0-9０-９]+条")
RE_CIRCLED_HEAD = re.compile(r"^[①-⑳]\S")


@dataclass(frozen=True)
class Grammar:
    name: str
    chapter: re.Pattern[str]
    section: re.Pattern[str]
    article: re.Pattern[str]
    toc_entry: re.Pattern[str]


@lru_cache(maxsize=4)
def load_grammar(name: str) -> Grammar:
    cfg = yaml.safe_load((CONFIGS / "grammars" / f"{name}.yaml").read_text(encoding="utf-8"))
    p = cfg["patterns"]
    return Grammar(
        name=cfg["name"],
        chapter=re.compile(p["chapter"]),
        section=re.compile(p["section"]),
        article=re.compile(p["article"]),
        toc_entry=re.compile(cfg["toc_entry"]),
    )


@lru_cache(maxsize=4)
def _inference(name: str) -> dict:
    cfg = yaml.safe_load((CONFIGS / "grammars" / f"{name}.yaml").read_text(encoding="utf-8"))
    return cfg["inference"]


def infer_grammar(lines: list[str]) -> str:
    """印字形から体裁を決める。既定は約款（`YAKKAN`）。

    **`jyusetsu` と判定するのは「条を 1 件も使っていない」ときだけにする。**
    片方の条件だけ（丸数字の見出しが多い）で切り替えると、丸数字を項に使う
    約款（group）を誤って jyusetsu にしてしまう。
    """
    inf = _inference(JYUSETSU)
    kanji = sum(1 for s in lines if RE_ARTICLE_KANJI.search(s))
    circled = sum(1 for s in lines if RE_CIRCLED_HEAD.match(s.strip()))
    if kanji <= inf["max_article_kanji_hits"] and circled >= inf["min_circled_heading_hits"]:
        return JYUSETSU
    return YAKKAN

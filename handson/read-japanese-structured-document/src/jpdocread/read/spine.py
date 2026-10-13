"""P1 — 本文の背骨。S2 で確定した読み手方策を 1 か所に閉じ込める。

**確定事項（移植元の読み手の選定）**
  * 既定は R2（`AI_PARSE_DOCUMENT(LAYOUT)`）。E1 決勝の held-out 115p で
    正規化 CER 0.0334、R4 は 0.0658 だった。
  * R4 は課金ゼロの対照、原文と幾何の供給源として維持する。
  * R4 と R2 の不一致は差し替えの根拠ではなく、検証パスへ回す警報である。

R2 の生 Markdown は保持し、採点・構造入力で必要な場合だけ別途除去する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..common.textdist import disagreement
from .parse.markdown import strip_markdown
from .parse.r4_local import read_pages_text

# **既定は R2。** E1 決勝（PILOT 135p / held-out 115p・正規化・字数重み）の実測：
#   R2 = 0.0334、R4 = 0.0658。R2 が 2 倍良い。
# P20（20p）では逆に R4 が勝っていた（R4 0.0261 / R2 0.0492）が、これは P20 の
# **選定バイアス**による。P20 は `PDF_LINES` の文字数を主キーに選んだので、
# R4 自身のテキストレイヤが充実したページに偏っていた。
# → 反復用スライスを候補読み手由来の特徴で選ぶと、その読み手に有利に偏る。
#
# スタイル単位裁定は held-out 上で 0.0334 → 0.0307（8% 改善）にとどまり、
# しかも held-out 自身で当てはめた楽観値である。独立した較正集合が無いので
# **保留**とし、既定を単純に R2 にする。R4 は課金ゼロの対抗意見として警報に使う。
STYLE_READER: dict[str, str] = {}
DEFAULT_READER = "R2"

# `disagreement(R4, R2)` がこれを超えたページは P6（検証）に回す。
# S2 実測：超えた 5 ページの R4 平均 CER 0.117 / 超えない 15 ページ 0.018（6.5 倍）。
DISAGREEMENT_ALARM = 0.25


def reader_for(doc_id: str) -> str:
    # 親は manifest.json から style_id を引いていた。manifest は正解側の目録なので読まない
    # 。doc_id は `<content_id>--<style_id>` なので doc_id から取る
    # （41 文書すべてで manifest の style_id と一致することを確認済み）。
    style_id = doc_id.split("--", 1)[1] if "--" in doc_id else ""
    return STYLE_READER.get(style_id, DEFAULT_READER)


@dataclass
class Spine:
    doc_id: str
    reader: str
    pages: dict[int, str] = field(default_factory=dict)
    raw_pages: dict[int, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    query_ids: list[str] = field(default_factory=list)
    from_cache: bool = False
    missing_pages: list[int] = field(default_factory=list)
    alarms: list[int] = field(default_factory=list)


def read_spine(
    doc_id: str,
    pages: list[int] | None = None,
    with_alarm: bool = False,
    cache_only: bool = True,
) -> Spine:
    """1 文書の本文を読む。R2 の raw と採点用本文を分けて保持する。"""
    from .parse.r12_cortex import parse_doc

    reader = reader_for(doc_id)
    local_results = read_pages_text(doc_id)
    local = {pt.page: pt.text for pt in local_results}
    want = pages or sorted(local)

    if reader == "R4" and not with_alarm:
        return Spine(
            doc_id,
            reader,
            {p: local.get(p, "") for p in want},
            raw_pages={p: local.get(p, "") for p in want},
        )

    ranges = [(p - 1, p) for p in want]
    res = parse_doc(doc_id, reader="R2", page_filter=ranges, cache_only=cache_only)
    raw = {p: res.pages.get(p, "") for p in want}
    remote = {p: strip_markdown(raw[p]) for p in want}

    chosen = remote if reader == "R2" else {p: local.get(p, "") for p in want}
    sp = Spine(
        doc_id,
        reader,
        chosen,
        raw_pages=raw,
        errors=[res.err] if res.err else [],
        query_ids=[res.query_id] if res.query_id else [],
        from_cache=res.from_cache,
        missing_pages=[p for p in want if p not in res.pages],
    )
    if with_alarm:
        sp.alarms = [
            p
            for p in want
            if disagreement(local.get(p, ""), remote.get(p, "")) > DISAGREEMENT_ALARM
        ]
    return sp

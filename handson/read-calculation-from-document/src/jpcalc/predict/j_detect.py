"""J 段：計算・判定の候補の検出。

決定的な候補検出（J1）：pdoc の木を走査し、計算・判定の手掛かりを持つ単位に印を付ける。
候補の一覧は段 K に渡し、K が候補だけから規定を数え上げる（文書全体の自由な一次検出は LLM にさせない）。
"""

from __future__ import annotations

import functools
import re
import unicodedata

from ..common.tunables import tun
from .context import footnote_items
from .policy_index import PolicyIndex

# 肯定の手掛かり（文の型）
CUES = [
    r"の額は",
    r"額とします",
    r"を差し引",
    r"いずれか(低|高|少な|多)い",
    r"を限度と",
    r"を乗じ",
    r"を上限",
    r"を下回",
    r"を上回",
    r"に相当する額",
    r"日数",
    r"回数",
    r"支払いません",
    r"支払わない",
    r"お支払いしません",
    r"翌日から起算",
    r"を経過する日",
    r"以上",
    r"を超え",
    r"未満",
    r"以下",
    r"端数",
    r"切り捨て",
    r"切り上げ",
    r"割合",
    r"按分",
    r"合計額",
    r"経過",
    r"待機",
    r"記載がない場合",
    r"記載がないとき",
    r"限度額",
    r"支払う(か|かどうか)",
    r"判定",
    r"該当する場合",
    r"通算",
]
CUE_RE = re.compile("|".join(CUES))
# 否定の手掛かり（設例・参照だけの文）。設例の囲みは別扱いで候補から外す
NEG_RE = re.compile(r"^(この(条|特約)の規定は|前条の規定にかかわらず、?$)")
RULE_TABLES = {
    "grade_schedule",
    "rate",
    "benefit_schedule",
    "coefficient",
    "surgery_schedule",
    "plan_matrix",
    "exclusions",
    "items",
    "conditions",
}
RULE_FIGURES = {"flowchart", "timeline", "steps", "tree", "matrix"}
CONST = re.compile(r"\{const:([^}]+)\}")


@functools.lru_cache(maxsize=64)
def _compile_cues(cues: tuple[str, ...]) -> re.Pattern:
    return re.compile("|".join(cues))


def cue_re() -> re.Pattern:
    """手掛かりの正規表現。上書き（j1.cues・j1.cues_extra）が無ければ CUE_RE そのもの。"""
    cues = tun("j1.cues", CUES)
    extra = tun("j1.cues_extra", ())
    if cues is CUES and not extra:
        return CUE_RE
    return _compile_cues(tuple(cues) + tuple(extra))


EXAMPLE_BOX = re.compile(r"^box(?:_.+|\d+)_note$")  # JSON：box_<…>_note、pdoc：box<N>_note


def _is_example_box(ix: PolicyIndex, uid: str) -> bool:
    return any(EXAMPLE_BOX.match(a) for a in [uid, *ix.ancestors(uid)])


def _cell(c) -> str:
    return (c.get("text") if isinstance(c, dict) else str(c or "")) or ""


def table_text(ix: PolicyIndex, n: dict, max_rows: int = 12) -> str:
    """表の候補の本文：題名＋見出し行＋各行の先頭 2 セル（K が判定の条件の行を読めるように）。"""
    rows = n.get("grid") or []
    lines = [" | ".join(_cell(c) for c in r[:2]) for r in rows[:max_rows]]
    return ix.expand(" ／ ".join([n.get("caption") or ""] + lines))


def figure_text(ix: PolicyIndex, n: dict) -> str:
    """図の候補の本文：題名＋ノードの文言と分岐のラベル付きの辺（K が判定の流れを読めるように）。"""
    d = n.get("diagram") or {}
    label = {x.get("id"): x.get("label") or "" for x in d.get("nodes") or []}
    edges = [
        f"{label.get(e.get('from'), '')}→{('（' + e['label'] + '）') if e.get('label') else ''}{label.get(e.get('to'), '')}"
        for e in d.get("edges") or []
    ]
    facts = [str(f) for f in d.get("facts") or []][:12]
    return ix.expand(" ／ ".join([n.get("caption") or ""] + edges + facts))


def formula_text(n: dict) -> str:
    """算式の本文。JSON は alt、pdoc は terms に入る。"""
    return n.get("alt") or "".join(
        t.get("text", "") for t in n.get("terms") or [] if isinstance(t, dict)
    )


def candidates(ix: PolicyIndex) -> list[dict]:
    """候補の単位（id・種類・手掛かり・本文）。設例の囲みの中は除く（説明であり規範ではない）。"""
    out = []
    cre = cue_re()
    rule_tables = tun("j1.rule_tables", RULE_TABLES)
    rule_figures = tun("j1.rule_figures", RULE_FIGURES)
    max_rows = tun("j1.table_max_rows", 12)
    # 条の題名の手掛かり（既定は空＝働かない）。題名がこの語を含む条の段落・号は、本文に手掛かり語が無くても候補にする
    title_cues = tuple(tun("j1.title_cues", ()))
    # 期日の文面の型（正規表現の一覧。既定は空＝働かない）。手掛かり語の無い段落・号でも、型に当たれば候補にする
    deadline_res = [(i, re.compile(p)) for i, p in enumerate(tun("j1.deadline_patterns", ()))]
    for uid in ix.order:
        n = ix.by_id[uid]
        if _is_example_box(ix, uid):
            continue
        t = n.get("type")
        kind = n.get("kind")
        cues: list[str] = []
        text = ""
        if kind in ("paragraph", "item") or (t == "paragraph"):
            raw = n.get("text") or ""
            text = ix.expand(raw)
            if CONST.search(raw):
                cues.append("const")
            cues += sorted({m.group(0) for m in cre.finditer(text)})
            if NEG_RE.search(text):
                cues = []
            elif title_cues and not cues:
                title = ix.expand(
                    (ix.by_id.get(ix.container(uid) or "", {}) or {}).get("title") or ""
                )
                hit = sorted({w for w in title_cues if w in title})
                if hit:
                    cues = [f"title:{w}" for w in hit]
            if deadline_res and not cues and not NEG_RE.search(text):
                nt = unicodedata.normalize("NFKC", text)
                cues = [f"deadline:{i}" for i, r in deadline_res if r.search(nt)]
        elif t == "table" and n.get("semantic_type") in rule_tables:
            cues.append(f"table:{n.get('semantic_type')}")
            text = table_text(ix, n, max_rows)
        elif t == "figure" and (n.get("diagram") or {}).get("kind") in rule_figures:
            cues.append(f"figure:{n['diagram']['kind']}")
            text = figure_text(ix, n)
        elif t == "formula":
            cues.append("formula")
            text = ix.expand(formula_text(n))
        elif t == "footnotes":
            for it in footnote_items(n):
                tx = ix.expand(it["raw"])
                c = (["const"] if CONST.search(it["raw"]) else []) + sorted(
                    {m.group(0) for m in cre.finditer(tx)}
                )
                if c:
                    out.append(
                        {
                            "id": it["id"],
                            "kind": "footnote",
                            "cues": c,
                            "text": tx,
                            "container": ix.container(uid) or uid,
                        }
                    )
            continue
        if cues:
            out.append(
                {
                    "id": uid,
                    "kind": t or kind,
                    "cues": cues,
                    "text": text,
                    "container": ix.container(uid) or uid,
                }
            )
    return out


def render_candidates(ix: PolicyIndex, cands: list[dict], max_chars: int = 220) -> str:
    by: dict[str, list[dict]] = {}
    for c in cands:
        by.setdefault(c["container"], []).append(c)
    lines = []
    for cont, cs in by.items():
        n = ix.by_id.get(cont, {})
        lines.append(f"■ [{cont}] {ix.citation(cont)}（{ix.expand(n.get('title'))}）")
        for c in cs:
            t = c["text"] if len(c["text"]) <= max_chars else c["text"][:max_chars] + "…"
            lines.append(f"  - [{c['id']}]（{c['kind']}）{t}")
    return "\n".join(lines)

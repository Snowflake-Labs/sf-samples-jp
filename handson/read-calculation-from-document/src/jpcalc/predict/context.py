"""D 段に渡す文脈を決定的に組み立てる。

根拠単位（段落・表・図・算式・脚注の id）から：
- その単位を含む条（または特約の条・別表の節）の全段落（{const:} は値に、{term:} は定義語に展開済み）
- 条の中の表（格子を文字にしたもの）・図（ノードと辺）・算式・設例の囲み
- 参照されている定数の一覧（キー・表記・数値パーサで解決した値と単位。解決できないものは unresolved）
- 表ブロックの自動読み取り結果（キー → 値の行）
を返す。LLM に金額や表の値を書き写させないため、値はすべてここで確定させる。
"""

from __future__ import annotations

import json
import re

from ..common import numparse as N
from . import tables as TB
from .policy_index import PolicyIndex

CONST = re.compile(r"\{const:([^}]+)\}")
REF = re.compile(r"\{ref:([^}|]+)")


def referenced(ix: PolicyIndex, units: list[str]) -> list[str]:
    """選ばれた単位の本文が {ref:} で参照する先（別表など）。参照先の節の中身ごと文脈に入れる。"""
    out: list[str] = []
    for u in units:
        n = ix.by_id.get(ix.resolve(u)) or {}
        raw = json.dumps(n, ensure_ascii=False)
        for tgt in REF.findall(raw):
            if tgt in ix.by_id and tgt not in out:
                out.append(tgt)
    return out


def _block_lines(ix: PolicyIndex, b: dict, consts: set[str]) -> list[str]:
    t = b.get("type")
    bid = b.get("id", "")
    raw = json.dumps(b, ensure_ascii=False)
    consts.update(CONST.findall(raw))
    if t == "table":
        g = TB.grid_texts(ix, bid)
        cap = ix.expand(b.get("caption"))
        out = [f"[{bid}] 表「{cap}」（semantic_type={b.get('semantic_type')}）"]
        out += ["  | " + " | ".join(row) + " |" for row in g]
        return out
    if t == "figure":
        dg = b.get("diagram") or {}
        out = [f"[{bid}] 図「{ix.expand(b.get('caption'))}」（kind={dg.get('kind')}）"]
        labels = {n["id"]: ix.expand(n.get("label")) for n in dg.get("nodes", [])}
        for n in dg.get("nodes", []):
            out.append(f"  ノード {n['id']}（{n.get('shape')}）: {labels[n['id']]}")
        for e in dg.get("edges", []):
            lab = f"［{ix.expand(e.get('label'))}］" if e.get("label") else ""
            out.append(
                f"  辺 {labels.get(e['from'], e['from'])} →{lab} {labels.get(e['to'], e['to'])}"
            )
        for f in b.get("facts") or []:
            out.append(f"  説明: {ix.expand(f)}")
        return out
    if t == "formula":
        terms = []
        for x in b.get("terms", []):
            terms.append(ix.expand(x.get("box") or x.get("op") or x.get("text") or ""))
        return [f"[{bid}] 算式: " + " ".join(terms), f"  （説明）{ix.expand(b.get('alt'))}"]
    if t == "box":
        out = [f"[{bid}] 囲み「{ix.expand(b.get('title'))}」"]
        for c in b.get("blocks", []):
            out += ["  " + x for x in _block_lines(ix, c, consts)]
        return out
    if t == "paragraph":
        return [f"[{bid}] {ix.expand(b.get('text'))}"]
    if t == "footnotes":
        out = [f"[{bid}] 脚注"]
        for it in footnote_items(b):
            consts.update(CONST.findall(it["raw"]))
            out.append(f"  [{it['id']}] ※{it['n']} {ix.expand(it['raw'])}")
        return out
    if t == "list":
        return [f"[{bid}] " + "／".join(ix.expand(i.get("text")) for i in b.get("items", []))]
    return []


def footnote_items(b: dict) -> list[dict]:
    """脚注ブロックの各注（単位 id は `<脚注ブロック id>__n<番号>`）。"""
    return [
        {"id": f"{b.get('id')}__n{x.get('n')}", "n": x.get("n"), "raw": x.get("text") or ""}
        for x in (b.get("notes") or b.get("items") or [])
    ]


def _node_lines(ix: PolicyIndex, n: dict, consts: set[str], depth: int = 0) -> list[str]:
    out = []
    ind = "  " * depth
    if n.get("kind") in (
        "article",
        "appendix_section",
        "appendix",
        "rider",
        "chapter",
        "section",
        "part",
    ):
        out.append(f"{ind}[{n['id']}] {ix.citation(n['id'])}（{ix.expand(n.get('title'))}）")
    elif n.get("text") is not None or n.get("kind") in ("paragraph", "item"):
        raw = n.get("text") or ""
        consts.update(CONST.findall(raw))
        out.append(f"{ind}[{n['id']}] {ix.citation(n['id'])} {ix.expand(raw)}")
    for b in n.get("blocks") or []:
        out += [ind + "  " + x for x in _block_lines(ix, b, consts)]
    for c in n.get("children") or []:
        out += _node_lines(ix, c, consts, depth + 1)
    return out


def resolve_const(text: str) -> dict:
    try:
        q = N.parse(text)
        if q.unit == "UNLIMITED":
            return {
                "text": text,
                "value": None,
                "unit": "UNLIMITED",
                "error": "無制限は数値にできない",
            }
        v = q.value
        if not isinstance(v, int):
            return {"text": text, "value": None, "unit": q.unit, "error": f"整数でない値 {v}"}
        return {"text": text, "value": v, "unit": q.unit}
    except N.NumParseError as e:
        return {"text": text, "value": None, "unit": None, "error": str(e)}


def build(ix: PolicyIndex, units: list[str]) -> dict:
    """根拠単位の集合 → 文脈（本文行・定数表・表の読み取り結果・含まれる単位 id）。"""
    containers: list[str] = []
    for u in units:
        c = ix.container(u) or u
        if c not in containers:
            containers.append(c)
    for tgt in referenced(ix, units):  # 参照先：別表・別の条（既に含む条の中なら足さない）
        if tgt not in containers and not any(c in ix.ancestors(tgt) for c in containers):
            containers.append(tgt)
    consts: set[str] = set()
    lines: list[str] = []
    table_ids: list[str] = []
    for c in containers:
        n = ix.by_id.get(c)
        if not n:
            continue
        lines += _node_lines(ix, n, consts)
        lines.append("")
    for u in units:  # 条の外にある単位（脚注など）
        if u in ix.by_id and not any(u == c or c in ix.ancestors(u) for c in containers):
            b = ix.by_id[u]
            lines += _node_lines(ix, b, consts) if "kind" in b else _block_lines(ix, b, consts)
    for c in containers:
        for oid in ix.order:
            if (oid == c or c in ix.ancestors(oid)) and ix.by_id[oid].get("type") == "table":
                table_ids.append(oid)
    const_table = {k: resolve_const(ix.constants[k]) for k in sorted(consts) if k in ix.constants}
    tables = {}
    for t in table_ids:
        try:
            lay = TB.auto_layout(ix, t)
            tables[t] = {"rows": TB.read_rows(ix, t, **lay), "layout": lay}
        except TB.TableReadError as e:
            tables[t] = {"rows": None, "error": str(e)}
    return {
        "text": "\n".join(lines).strip(),
        "constants": const_table,
        "tables": tables,
        "containers": containers,
    }

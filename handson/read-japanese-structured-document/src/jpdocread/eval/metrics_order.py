"""文書順の nTED（C-012）。

`metrics_structure.nted` は gold の木を **`elements.jsonl` の行順** で並べる。契約書の
`elements.jsonl` は `element_id` の文字列順（a1, a10, a10_p1, …, a2）で並んでいるため、
条が 10 以上ある文書では「第十条以降が第二条の前にある」木と比べることになり、
正しく読めた木でも距離が大きく出る（dev 56 文書で平均 0.324 のうち大半がこれ。C-012）。

ここでは gold の兄弟を **`layout.json.pages[].reading_order`**（gold 自身の読み順）で並べ直し、
同じ Zhang–Shasha・同じ正規化で距離を測る。既存の `nted` は式を変えずに残す。

- `reading_order` に現れないノード（`pre`・`sig`・`sch1` などの入れ物）は、子孫の最小位置を使う。
- 子孫も含めて現れないノードは、`elements.jsonl` の行番号を大きな下駄付きで使う（`n_unordered` に数える）。
"""

from __future__ import annotations

from .gold import load_elements, load_layout
from .metrics_structure import LabeledTree, _flat, _postorder, pred_labeled_tree, tree_edit_distance

_UNORDERED = 10**9


def gold_reading_rank(doc_id: str) -> dict[str, int]:
    rank: dict[str, int] = {}
    for page in load_layout(doc_id).get("pages") or []:
        for eid in page.get("reading_order") or []:
            rank.setdefault(eid, len(rank))
    return rank


def gold_labeled_tree_doc(doc_id: str) -> tuple[LabeledTree, int]:
    els = [e for e in load_elements(doc_id) if e.get("node_kind")]
    ids = {e["element_id"] for e in els}
    rank = gold_reading_rank(doc_id)
    children: dict[str, list[str]] = {}
    label: dict[str, tuple[str, str]] = {}
    roots: list[str] = []
    line: dict[str, int] = {}
    for i, e in enumerate(els):
        eid = e["element_id"]
        line[eid] = i
        label[eid] = (e["node_kind"], _flat(e.get("label") or ""))
        pid = e.get("parent_id")
        if pid in ids:
            children.setdefault(pid, []).append(eid)
        else:
            roots.append(eid)

    key: dict[str, int] = {}

    visiting: set[str] = set()

    def pos(eid: str) -> int:
        if eid not in key:
            if (
                eid in visiting
            ):  # parent_id の循環（_postorder は根から届かないので無視する。ここでも止める）
                return rank.get(eid, _UNORDERED)
            visiting.add(eid)
            own = rank.get(eid, _UNORDERED)
            key[eid] = min([own] + [pos(c) for c in children.get(eid, [])])
            visiting.discard(eid)
        return key[eid]

    for eid in ids:
        pos(eid)
    n_unordered = sum(1 for v in key.values() if v >= _UNORDERED)
    sort_key = {eid: (key[eid], line[eid]) for eid in ids}
    for v in children.values():
        v.sort(key=sort_key.get)
    roots.sort(key=sort_key.get)
    return _postorder(children, roots, label), n_unordered


def nted_doc(doc_id: str, tree) -> dict:
    """`nted` と同じ式（TED / max(|gold|, |pred|)）で、gold を文書順に並べたもの。"""
    g, n_unordered = gold_labeled_tree_doc(doc_id)
    p = pred_labeled_tree(tree)
    d = tree_edit_distance(g, p)
    denom = max(len(g), len(p)) or 1
    return {"nted_doc": round(d / denom, 6), "ted_doc": d, "n_unordered": n_unordered}

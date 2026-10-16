"""S60 — 読み取り結果 JSON の採点（採点側専用）。

入力は 2 つだけ：
  予測  JPDOCREAD_OUT/<doc_id>.json（S50 が出力した JSON。ステージ @<DB>.OUTPUT.RESULTS/<run_id>/）
  正解  JPDOCREAD_DOCS/<doc_id>/{answer.json, elements.jsonl, source.json, layout.json} と manifest.json

指標の関数と対応づけの規則は移植元のものをそのまま使う（式を変えると移植元の数値と比べられない）：
  本文   metrics_text.score_text（CER 生／正規化・文字 F1・最悪 10%）          親 eval/score.py
  引用   (node_kind, canonical_citation) の多重集合の直接測定                   親 eval/deliverable.py（D-14）
  構造   条・段落・号の引用集合 R/P                                            親 eval/e7_structure.py
         nTED・番号違反（intrinsic / gold 由来）                               親 eval/metrics_structure.py
  表     gold 表の頁上の予測表から中身で対応 → score_table                      親 eval/w15_tables.py
  図     gold 図 bbox に最も重なる予測図 → score_figure（ラベルで照合）          親 eval/w15_figures.py・e4
  参照   (参照元の引用, 参照先の引用) の集合の R（到達可能／全体）・P・F1          親 eval/w18_refs.py（W18・W19）
  頑健性 同一 content 異スタイル対の style_divergence = 1 − 文字F1(予測A, 予測B)

親との違い：構造の指標は、親が木（Tree）を直接採点していたのに対し、ここでは出力 JSON の
`outline`（木の全ノード）から木を組み直して採点する。成果物そのものを測るためである。
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from ..common.paths import OUT
from ..read.structure.tree import Node, Tree, canonical_citation
from . import contract_semantics as CS
from .gold import assert_checksums, load_elements, load_gold, load_source
from .metrics_figregion import figure_region_scores, summarize_figure_regions
from .metrics_figure import score_figure
from .metrics_order import nted_doc
from .metrics_span import span_scores, summarize_spans
from .metrics_structure import nted, number_integrity
from .metrics_table import norm_cell, score_table
from .metrics_text import char_f1, score_text

BODY_KINDS = ("paragraph", "item")
RE_CELL_ID = re.compile(r"^(?P<tid>.+)__r(?P<r>\d+)c(?P<c>\d+)$")


class MissingPrediction(FileNotFoundError):
    """出力 JSON が無い（空として採点せず、欠落として数える）。"""


def load_pred(doc_id: str, out_dir: Path | None = None) -> dict:
    p = (out_dir or OUT) / f"{doc_id}.json"
    if not p.exists():
        raise MissingPrediction(str(p))
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 本文


def text_scores(doc_id: str, pred: dict):
    pages = {int(p["number"]): p.get("text") or "" for p in pred.get("pages") or []}
    gold = {p.number: p.text for p in load_gold(doc_id).pages}
    return score_text(pages, gold)


# ---------------------------------------------------------------- 引用（主指標）


def citation_scores(doc_id: str, pred: dict) -> tuple[dict, list[dict]]:
    """成果物の各要素の (node_kind, canonical_citation) を gold の多重集合と突き合わせる（D-14）。"""
    gold: Counter = Counter()
    for e in load_elements(doc_id):
        k = e.get("node_kind")
        if k in BODY_KINDS:
            gold[(k, canonical_citation(e.get("citation") or ""))] += 1
    pc: Counter = Counter()
    n = n_cited = 0
    for e in pred.get("elements") or []:
        n += 1
        cit = (e.get("citation") or "").strip()
        n_cited += bool(cit)
        pc[(e.get("node_kind"), canonical_citation(cit))] += 1
    per_kind: dict[str, dict[str, int]] = {}
    errors: list[dict] = []
    for (kind, cit), v in pc.items():
        k = kind or "∅"
        acc = per_kind.setdefault(k, {"n": 0, "ok": 0, "bad": 0})
        ok = min(v, gold.get((kind, cit), 0))
        acc["n"] += v
        acc["ok"] += ok
        acc["bad"] += v - ok
        if v - ok:
            errors.append(
                {
                    "node_kind": k,
                    "citation": cit,
                    "n_pred": v,
                    "n_gold": gold.get((kind, cit), 0),
                    "n_wrong": v - ok,
                }
            )
    bad = sum(a["bad"] for a in per_kind.values())
    n_gold = sum(gold.values())
    n_ok = sum(a["ok"] for a in per_kind.values())
    return {
        "n_elements": n,
        "n_cited": n_cited,
        "n_wrong": bad,
        "citation_error_rate": round(bad / n, 6) if n else 0.0,
        # C-004：引用誤り率は予測した要素だけを分母にするので取りこぼしが見えない。
        # gold の本文要素のうち、引用が一致した予測を持つ割合（同じ多重集合の突き合わせを gold 側から数える）
        "n_gold": n_gold,
        "n_matched": n_ok,
        "coverage": round(n_ok / n_gold, 6) if n_gold else 0.0,
        "per_kind": per_kind,
    }, errors


# ---------------------------------------------------------------- 構造


def tree_from_outline(doc_id: str, pred: dict) -> Tree:
    """出力 JSON の `outline` から木を組み直す（移植元の Tree と同じノード集合・親子・順序）。"""
    t = Tree(doc_id=doc_id)
    for o in pred.get("outline") or []:
        t.add(
            Node(
                node_id=o["id"],
                kind=o["node_kind"],
                label=o.get("label") or "",
                heading=o.get("title") or "",
                citation=o.get("citation") or "",
                parent_id=o.get("parent_id"),
                pages=[o["page"]] if o.get("page") is not None else [],
            )
        )
    return t


def _pr(gold: list[str], pred: list[str]) -> tuple[float, float, int, int, int]:
    g, p = set(gold), set(pred)
    tp = len(g & p)
    return (tp / len(g) if g else 0.0), (tp / len(p) if p else 0.0), tp, len(g), len(p)


def structure_scores(doc_id: str, pred: dict) -> dict:
    tree = tree_from_outline(doc_id, pred)
    out: dict = {}
    for kind in ("article", "paragraph", "item"):
        g = [
            canonical_citation(e.get("citation") or "")
            for e in load_elements(doc_id)
            if e.get("node_kind") == kind and e.get("citation")
        ]
        p = [canonical_citation(n.citation) for n in tree.nodes.values() if n.kind == kind]
        r, pr, tp, ng, np_ = _pr(g, p)
        out[kind] = {
            "recall": round(r, 4),
            "precision": round(pr, 4),
            "tp": tp,
            "gold": ng,
            "pred": np_,
        }
    out["nted"] = nted(doc_id, tree)
    out["nted_doc"] = nted_doc(doc_id, tree)  # C-012：gold を文書順に並べた nTED
    ni = number_integrity(doc_id, tree)
    out["number_violations_intrinsic"] = ni["number_violations_intrinsic"]
    out["number_violations_gold_origin"] = ni["number_violations_gold_origin"]
    out["number_violations"] = ni["number_violations"]
    return out


# ---------------------------------------------------------------- 表


def grid_from_elements(doc_id: str, table_id: str) -> list[dict] | None:
    """gold の `cell` 要素から格子を復元する（親 eval/shots.py と同じ規則：縦優先の占有）。"""
    occ: dict[tuple[int, int], dict] = {}
    for e in load_elements(doc_id):
        if e.get("kind") != "cell":
            continue
        m = RE_CELL_ID.match(e.get("element_id") or "")
        if not m or m.group("tid") != table_id:
            continue
        occ[(int(m.group("r")), int(m.group("c")))] = e
    if not occ:
        return None
    max_r = max(r for r, _ in occ)
    max_c = max(c for _, c in occ)
    rowspan: dict[tuple[int, int], int] = {}
    for r, c in occ:
        n = 1
        while r + n <= max_r and (r + n, c) not in occ:
            n += 1
        rowspan[(r, c)] = n
    covered = {(r + k, c) for (r, c), n in rowspan.items() for k in range(1, n)}
    colspan: dict[tuple[int, int], int] = {}
    for r, c in occ:
        n = 1
        while c + n <= max_c and (r, c + n) not in occ and (r, c + n) not in covered:
            n += 1
        colspan[(r, c)] = n
    area = sum(rowspan[k] * colspan[k] for k in occ)
    if area != (max_r + 1) * (max_c + 1):
        raise ValueError(f"格子の復元に失敗（{doc_id}#{table_id}）: 面積 {area}")
    hp = ((load_source(doc_id).get("derived") or {}).get("tables") or {}).get(table_id, {}).get(
        "header_path"
    ) or {}
    return [
        {
            "row": r,
            "col": c,
            "rowspan": rowspan[(r, c)],
            "colspan": colspan[(r, c)],
            "text": e.get("text") or "",
            "is_header": (e.get("element_id") not in hp),
        }
        for (r, c), e in sorted(occ.items())
    ]


def _best_match(cands: list[list[dict]], gold_grid: list[dict]) -> list[dict] | None:
    """同一ページの予測表のうち、gold のセル本文との一致数が最大のもの（2 件以上一致が条件）。"""
    gold_texts = {norm_cell(c.get("text")) for c in gold_grid if norm_cell(c.get("text"))}
    if not gold_texts:
        return None
    best, best_hit = None, 0
    for g in cands:
        hit = len({norm_cell(c["text"]) for c in g if norm_cell(c["text"])} & gold_texts)
        if hit > best_hit:
            best, best_hit = g, hit
    return best if best_hit >= 2 else None


def table_scores(doc_id: str, pred: dict) -> list[dict]:
    preds = pred.get("tables") or []
    rows = []
    for e in load_elements(doc_id):
        if e.get("kind") != "table":
            continue
        gold = grid_from_elements(doc_id, e["element_id"])
        if not gold:
            continue
        cands = [t["grid"] for t in preds if set(t.get("pages") or []) & set(e.get("pages") or [])]
        best = _best_match(cands, gold) or []
        shape = (
            max(c["row"] + c["rowspan"] for c in gold),
            max(c["col"] + c["colspan"] for c in gold),
        )
        sc = score_table(gold, best, shape, None)
        rows.append(
            {
                "table_id": e["element_id"],
                "matched": bool(best),
                "cell_f1": round(sc.cell_f1, 4),
                "header_path_acc": round(sc.header_path_acc, 4),
                "is_header_acc": round(sc.is_header_acc, 4),
                "n_gold_cells": sc.n_gold_cells,
                "n_pred_cells": sc.n_pred_cells,
            }
        )
    return rows


def table_span_scores(doc_id: str, pred: dict, tables: list[dict]) -> dict:
    """ページ・段をまたぐ表の採点（eval/metrics_span.py）。`tables` は `table_scores` の結果。"""
    gold_tables = [e for e in load_elements(doc_id) if e.get("kind") == "table"]
    grids = {}
    for e in gold_tables:
        g = grid_from_elements(doc_id, e["element_id"])
        if g:
            grids[e["element_id"]] = g
    f1 = {t["table_id"]: t["cell_f1"] for t in tables}
    return span_scores(gold_tables, grids, pred.get("tables") or [], f1)


# ---------------------------------------------------------------- 図


def _ov(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def gold_graph(doc_id: str, fig_id: str) -> tuple[list[dict], list[dict]]:
    """gold のグラフに `figure_node` 要素の bbox を貼って返す（親 eval/e4_figures.py と同じ）。"""
    figs = (load_source(doc_id).get("derived") or {}).get("figures") or {}
    g = (figs.get(fig_id) or {}).get("graph") or {}
    nodes = [dict(n) for n in (g.get("nodes") or [])]
    boxes = {}
    for e in load_elements(doc_id):
        if e.get("kind") != "figure_node":
            continue
        eid = e.get("element_id") or ""
        if eid.startswith(f"{fig_id}::"):
            boxes[eid.split("::", 1)[1]] = e.get("bboxes")
    for n in nodes:
        if n.get("id") in boxes:
            n["bboxes"] = boxes[n["id"]]
    return nodes, list(g.get("edges") or [])


def figure_scores(doc_id: str, pred: dict) -> list[dict]:
    preds = pred.get("figures") or []
    rows = []
    for e in load_elements(doc_id):
        if e.get("kind") != "figure":
            continue
        gn, ge = gold_graph(doc_id, e["element_id"])
        if not gn:
            continue
        page = (e.get("pages") or [None])[0]
        gbox = (e.get("bboxes") or [None])[0]
        cands = [f for f in preds if f.get("pages") == [page]] if gbox else []
        best = max(cands, key=lambda f: _ov(f["bbox"], gbox), default=None)
        if best is not None and _ov(best["bbox"], gbox) <= 0:
            best = None
        pn = (best or {}).get("nodes") or []
        pe = (best or {}).get("edges") or []
        sc = score_figure(gn, ge, pn, pe)
        rows.append(
            {
                "figure_id": e["element_id"],
                "matched": best is not None,
                # 予測図が gold の図をどれだけ覆うか（親 W17 は 0.7 以上の図だけを採点した）
                "containment": round(_ov(best["bbox"], gbox) / _area(gbox), 4)
                if best and _area(gbox)
                else 0.0,
                "has_graph": bool(best and best.get("source") == "AI_COMPLETE_opus5"),
                "node_f1": round(sc.node_f1, 4),
                "edge_f1": round(sc.edge_f1, 4),
                "path_f1": round(sc.path_f1, 4),
                "role_acc": round(sc.role_acc, 4) if sc.role_acc is not None else None,
                "n_crossings_gold": sc.n_crossings_gold,
                "n_gold_nodes": sc.n_gold_nodes,
                "n_gold_edges": sc.n_gold_edges,
            }
        )
    return rows


# ---------------------------------------------------------------- 参照関係


def gold_refs(doc_id: str) -> tuple[set[tuple[str, str]], Counter]:
    """gold の参照を (参照元の引用, 参照先の引用) に写す（親 eval/w18_refs.gold_pairs と同じ定義）。

    空・自己参照は単位の定義上除く。引用に写せない参照（参照元が表セル・脚注・描画されない要素）は
    捨てずに参照元の種別ごとに数え、全体の再現率の分母に入れる（必ず FN）。
    """
    els = {e["element_id"]: e for e in load_elements(doc_id)}
    pairs: set[tuple[str, str]] = set()
    unmapped: Counter = Counter()
    for r in load_source(doc_id)["derived"].get("refs") or []:
        f, t = els.get(r["from_id"]), els.get(r["to_id"])
        if not f or not t:
            unmapped["missing_element"] += 1
            continue
        fc = canonical_citation(f.get("citation") or "")
        tc = canonical_citation(t.get("citation") or "")
        if fc and tc and fc == tc:
            continue
        if not fc or not tc:
            unmapped[f.get("node_kind") or f.get("kind") or "?"] += 1
            continue
        pairs.add((fc, tc))
    return pairs, unmapped


def ref_scores(doc_id: str, pred: dict) -> dict:
    """成果物の `refs` を gold の引用対と突き合わせる。"""
    g, unmapped = gold_refs(doc_id)
    p = {
        (
            canonical_citation(r.get("from_citation") or ""),
            canonical_citation(r.get("to_citation") or ""),
        )
        for r in pred.get("refs") or []
    }
    p = {(f, t) for f, t in p if f and t}  # 移植元の resolve_refs は空の引用の対を作らない
    return {
        "gold_reachable": len(g),
        "gold_unreachable": sum(unmapped.values()),
        "gold_unreachable_by_kind": dict(unmapped),
        "pred": len(p),
        "tp": len(g & p),
    }


def summarize_refs(rows: list[dict]) -> dict:
    """文書別の件数を合計してから率にする（親 W18 と同じ集約）。"""
    tot: Counter = Counter()
    kinds: Counter = Counter()
    for r in rows:
        for k in ("gold_reachable", "gold_unreachable", "pred", "tp"):
            tot[k] += r[k]
        kinds.update(r["gold_unreachable_by_kind"])
    rr = tot["tp"] / tot["gold_reachable"] if tot["gold_reachable"] else 0.0
    pr = tot["tp"] / tot["pred"] if tot["pred"] else 0.0
    ga = tot["gold_reachable"] + tot["gold_unreachable"]
    return {
        **{k: tot[k] for k in ("gold_reachable", "gold_unreachable", "pred", "tp")},
        "gold_unreachable_by_kind": dict(kinds.most_common()),
        "recall_reachable": round(rr, 4),
        "precision": round(pr, 4),
        "f1_reachable": round(2 * rr * pr / (rr + pr), 4) if rr + pr else 0.0,
        "recall_all": round(tot["tp"] / ga, 4) if ga else 0.0,
    }


# ---------------------------------------------------------------- 文書・コーパス


def score_document(doc_id: str, out_dir: Path | None = None) -> dict:
    """1 文書を採点する。予測が無ければ MissingPrediction を送出する（空で採点しない）。"""
    pred = load_pred(doc_id, out_dir)
    ts = text_scores(doc_id, pred)
    cit, errors = citation_scores(doc_id, pred)
    tables = table_scores(doc_id, pred)
    return {
        "doc_id": doc_id,
        "style_id": doc_id.split("--", 1)[1],
        "content_id": doc_id.split("--", 1)[0],
        "genre": doc_id.split("-", 1)[0],
        "pred_run_id": (pred.get("provenance") or {}).get("run_id"),
        "text": {
            "cer": round(ts.cer_raw, 6),
            "cer_normalized": round(ts.cer_norm, 6),
            "char_f1": round(ts.char_f1_raw, 6),
            "cer_worst_decile": round(ts.cer_worst_decile, 6),
            "n_pages": ts.n_pages,
            "n_missing_pages": ts.n_missing_pages,
        },
        "citation": cit,
        "structure": structure_scores(doc_id, pred),
        "tables": tables,
        # ページ・段をまたぐ表（分断度・誤連結・またぎ方別のセル F1）。既存の tables の値は変えない
        "table_spans": table_span_scores(doc_id, pred, tables),
        "figures": figure_scores(doc_id, pred),
        # 図の領域（AI_COMPLETE の呼び出し単位）のうち正解の図と対応しないもの。既存の figures の値は変えない
        "figure_regions": figure_region_scores(load_elements(doc_id), pred),
        "refs": ref_scores(doc_id, pred),
        # 契約書の軸（C-007）：当事者・定義語
        "parties": CS.party_scores(doc_id, pred),
        "terms": CS.term_scores(doc_id, pred),
        "numbering_scheme": pred.get("numbering_scheme"),
        "pages": ts.per_page,
        "citation_errors": errors,
        "pred_text": "".join(p.get("text") or "" for p in pred.get("pages") or []),
    }


def _mean(v: list[float]) -> float:
    return round(sum(v) / len(v), 4) if v else 0.0


def summarize(docs: list[dict], missing: list[str], excluded: list[str]) -> dict:
    """文書別の採点を集約する（親と同じ集約：本文はページ平均、引用は要素の合計、表図は平均）。"""
    pages = [p for d in docs for p in d["pages"]]
    cers = sorted((p["cer"] for p in pages), reverse=True)
    k = max(1, round(len(cers) * 0.1)) if cers else 1
    n_el = sum(d["citation"]["n_elements"] for d in docs)
    n_bad = sum(d["citation"]["n_wrong"] for d in docs)
    n_gold_el = sum(d["citation"].get("n_gold", 0) for d in docs)
    n_match = sum(d["citation"].get("n_matched", 0) for d in docs)
    kinds: dict[str, dict[str, int]] = {}
    for d in docs:
        for kk, v in d["citation"]["per_kind"].items():
            a = kinds.setdefault(kk, {"n": 0, "ok": 0, "bad": 0})
            for f in ("n", "ok", "bad"):
                a[f] += v[f]
    struct: dict = {}
    for kind in ("article", "paragraph", "item"):
        tp = sum(d["structure"][kind]["tp"] for d in docs)
        g = sum(d["structure"][kind]["gold"] for d in docs)
        p = sum(d["structure"][kind]["pred"] for d in docs)
        struct[kind] = {
            "recall": round(tp / g, 4) if g else 0.0,
            "precision": round(tp / p, 4) if p else 0.0,
            "tp": tp,
            "gold": g,
            "pred": p,
        }
    tables = [t for d in docs for t in d["tables"]]
    figs = [f for d in docs for f in d["figures"]]
    figs_c70 = [f for f in figs if f["containment"] >= 0.7]
    # 異スタイル対：同じ content の 2 文書が両方とも採点対象にあるもの
    by_content: dict[str, list[dict]] = {}
    for d in docs:
        by_content.setdefault(d["content_id"], []).append(d)
    pairs = []
    for cid, ds in sorted(by_content.items()):
        if len(ds) == 2:
            a, b = ds
            pairs.append(
                {
                    "content_id": cid,
                    "styles": [a["style_id"], b["style_id"]],
                    "style_divergence": round(1 - char_f1(a["pred_text"], b["pred_text"]), 6),
                    "citation_error_rate": [
                        a["citation"]["citation_error_rate"],
                        b["citation"]["citation_error_rate"],
                    ],
                }
            )
    by_style: dict[str, list[float]] = {}
    for d in docs:
        by_style.setdefault(d["style_id"], []).append(d["citation"]["citation_error_rate"])
    return {
        "n_docs": len(docs),
        "n_missing_predictions": len(missing),
        "missing_predictions": missing,
        "excluded_shot_donors": excluded,
        "coverage": round(len(docs) / (len(docs) + len(missing)), 4) if docs or missing else 0.0,
        "text": {
            "n_pages": len(pages),
            "n_missing_pages": sum(d["text"]["n_missing_pages"] for d in docs),
            "cer": _mean([p["cer"] for p in pages]),
            "cer_normalized": _mean([p["cer_normalized"] for p in pages]),
            "char_f1": _mean([p["char_f1"] for p in pages]),
            "cer_worst_decile": round(sum(cers[:k]) / k, 4) if cers else 0.0,
            "cer_median": round(statistics.median(cers), 4) if cers else 0.0,
        },
        "citation": {
            "n_elements": n_el,
            "n_wrong": n_bad,
            "citation_error_rate": round(n_bad / n_el, 6) if n_el else 0.0,
            "n_gold": n_gold_el,
            "n_matched": n_match,
            "coverage": round(n_match / n_gold_el, 6) if n_gold_el else 0.0,  # C-004
            "per_kind": kinds,
            "n_docs_zero_error": sum(1 for d in docs if d["citation"]["n_wrong"] == 0),
        },
        "structure": {
            **struct,
            "nted_mean": _mean([d["structure"]["nted"]["nted"] for d in docs]),
            "nted_doc_mean": _mean([d["structure"]["nted_doc"]["nted_doc"] for d in docs]),
            "nted_doc_zero_docs": sum(
                1 for d in docs if d["structure"]["nted_doc"]["ted_doc"] == 0
            ),
            "nted_doc_n_unordered": sum(d["structure"]["nted_doc"]["n_unordered"] for d in docs),
            "number_violations_intrinsic": sum(
                d["structure"]["number_violations_intrinsic"] for d in docs
            ),
            "number_violations_gold_origin": sum(
                d["structure"]["number_violations_gold_origin"] for d in docs
            ),
        },
        "tables": {
            "n_gold_tables": len(tables),
            "n_unmatched": sum(1 for t in tables if not t["matched"]),
            "cell_f1": _mean([t["cell_f1"] for t in tables]),
            "header_path_acc": _mean([t["header_path_acc"] for t in tables]),
        },
        "figures": {
            "n_gold_figures": len(figs),
            "n_unmatched": sum(1 for f in figs if not f["matched"]),
            "n_with_graph": sum(1 for f in figs if f["has_graph"]),
            "node_f1": _mean([f["node_f1"] for f in figs]),
            "edge_f1": _mean([f["edge_f1"] for f in figs]),
            "path_f1": _mean([f["path_f1"] for f in figs]),
            # 親 W17 と同じ母集団（予測図領域が gold の図を 70% 以上覆うもの）
            "containment70": {
                "n": len(figs_c70),
                "node_f1": _mean([f["node_f1"] for f in figs_c70]),
                "edge_f1": _mean([f["edge_f1"] for f in figs_c70]),
                "path_f1": _mean([f["path_f1"] for f in figs_c70]),
            },
        },
        "table_spans": summarize_spans([d["table_spans"] for d in docs if "table_spans" in d]),
        "figure_regions": summarize_figure_regions(
            [d["figure_regions"] for d in docs if "figure_regions" in d]
        ),
        "refs": summarize_refs([d["refs"] for d in docs]),
        "parties": CS.summarize([d.get("parties") for d in docs]),
        "terms": CS.summarize([d.get("terms") for d in docs]),
        "style_pairs": {
            "n_pairs": len(pairs),
            "style_divergence_mean": _mean([p["style_divergence"] for p in pairs]),
            "pairs": pairs,
        },
        "citation_error_rate_by_style": {s: _mean(v) for s, v in sorted(by_style.items())},
        # doctype 別（doc_id の接頭辞。DB の列名は genre のまま）と番号方式別の引用誤り率・網羅率
        "by_doctype": _by(docs, lambda d: d.get("genre") or d["doc_id"].split("-", 1)[0]),
        "by_scheme": _by(docs, lambda d: d.get("numbering_scheme") or "none"),
    }


def _by(docs: list[dict], key) -> dict:
    out: dict[str, dict] = {}
    for d in docs:
        a = out.setdefault(
            key(d),
            {
                "n_docs": 0,
                "n_elements": 0,
                "n_wrong": 0,
                "n_gold": 0,
                "n_matched": 0,
                "_nted": [],
                "_nted_doc": [],
            },
        )
        a["n_docs"] += 1
        a["_nted"].append(d["structure"]["nted"]["nted"])
        a["_nted_doc"].append(d["structure"]["nted_doc"]["nted_doc"])  # C-012
        for f in ("n_elements", "n_wrong", "n_gold", "n_matched"):
            a[f] += d["citation"].get(f, 0)
    for a in out.values():
        a["citation_error_rate"] = (
            round(a["n_wrong"] / a["n_elements"], 6) if a["n_elements"] else 0.0
        )
        a["coverage"] = round(a["n_matched"] / a["n_gold"], 6) if a["n_gold"] else 0.0
        a["nted_mean"] = _mean(a.pop("_nted"))
        a["nted_doc_mean"] = _mean(a.pop("_nted_doc"))
    return dict(sorted(out.items()))


def evaluate(
    doc_ids: list[str],
    donors: list[str],
    out_dir: Path | None = None,
    subsets: dict[str, list[str]] | None = None,
) -> dict:
    """供出元を除いた文書を採点し、`{"summary", "docs", "integrity"}` を返す。"""
    targets = [d for d in doc_ids if d not in set(donors)]
    leaked = set(targets) & set(donors)
    if leaked:
        raise RuntimeError(f"供出元が採点対象に残っている: {sorted(leaked)}")
    integrity = assert_checksums(targets)
    docs, missing = [], []
    for d in targets:
        try:
            docs.append(score_document(d, out_dir))
        except MissingPrediction:
            missing.append(d)
    excl = sorted(set(donors) & set(doc_ids)) or list(donors)
    summary = summarize(docs, missing, excl)
    # 部分集合別（dev = 規則の設計に使った content・test = 凍結後に開く content。C-001）。
    # 集約は全体と同じ summarize。対象に 1 文書も無い部分集合は出さない（0 件を値として書かない）
    summary["subsets"] = {}
    for name, ids in (subsets if subsets is not None else _subsets()).items():
        ids = set(ids)
        sd = [d for d in docs if d["doc_id"] in ids]
        sm = [d for d in missing if d in ids]
        if sd or sm:
            sub = summarize(sd, sm, excl)
            sub["style_pairs"].pop("pairs", None)
            summary["subsets"][name] = sub
    return {"summary": summary, "docs": docs, "integrity": integrity}


def _subsets() -> dict[str, list[str]]:
    """部分集合が渡されなかったときの既定（無し）。

    移植元は configs/pipeline.yaml の slices を読んでいた。本ハンズオンではスライスがコーパス設定
    （configs/corpora/<name>.yaml）にあるので、呼び出し側（`jpdocread eval`・S60）が `subsets` に渡す。
    """
    return {}


def as_rows(result: dict, eval_run_id: str, pred_run_id: str) -> dict[str, list[dict]]:
    """評価 DB に入れる行（1 行 1 JSON）に分ける。"""
    docs = result["docs"]
    base = {"eval_run_id": eval_run_id, "pred_run_id": pred_run_id}
    return {
        "doc_metrics": [
            {
                **base,
                "doc_id": d["doc_id"],
                "style_id": d["style_id"],
                "genre": d["genre"],
                "metrics": {
                    k: d[k]
                    for k in (
                        "text",
                        "citation",
                        "structure",
                        "refs",
                        "parties",
                        "terms",
                        "numbering_scheme",
                    )
                },
                "tables": d["tables"],
                "table_spans": d["table_spans"],
                "figure_regions": d.get("figure_regions"),
                "figures": d["figures"],
            }
            for d in docs
        ],
        "page_metrics": [{**base, "doc_id": d["doc_id"], **p} for d in docs for p in d["pages"]],
        "element_errors": [
            {**base, "doc_id": d["doc_id"], **e} for d in docs for e in d["citation_errors"]
        ],
        "summary": [
            {
                **base,
                "summary": result["summary"],
                "integrity": {k: v for k, v in result["integrity"].items() if k != "evidence"},
            }
        ],
    }


__all__ = ["evaluate", "as_rows", "score_document", "summarize", "asdict"]

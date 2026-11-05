"""読み取りの採点（評価側。予測側から呼ばない）。

正解の layout.json の要素（条・章・項・号・表・算式・図）が、pdoc の同じ種類の単位に覆われるかを
ページと bbox の重なりで測る。正解と pdoc を 1 対 1 で対応させ、再現率（正解のうち対応が付いた割合）と
適合率（pdoc の単位のうち正解に対応した割合）を種類ごとに出す。値（本文・数値）は比べない。
項と号は、印字の形（①・（１）など）をどちらに組むかが文書と読み取りとで違うことがあるので、
両方をまとめた本文の単位（body）の被覆も出す（文の切れ目が読めているかを測る）。

対応の判定：同じページで、pdoc の単位の出所の bbox と正解の断片の bbox が重なり、重なりの面積が
小さいほうの bbox の 5 割以上。両方とも上原点の pt（pdfplumber と同じ座標系）。
1 つの単位の出所が複数の bbox（複数行）なら、ページごとに和の bbox にする。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from ..fetch.adapters import render

# 正解の要素の種類 → pdoc の単位の種類
KINDS: dict[str, str] = {
    "chapter": "chapter",
    "article": "article",
    "paragraph": "paragraph",
    "item": "item",
    "table": "table",
    "formula_box": "formula",
    "figure": "figure",
}
MIN_OVERLAP = 0.5
# 項と号をまとめた本文の単位
BODY_KINDS = ("paragraph", "item")


class ReadScoreError(ValueError):
    pass


@dataclass
class KindScore:
    n_gold: int = 0
    n_pred: int = 0
    n_match: int = 0

    @property
    def recall(self) -> float | None:
        return self.n_match / self.n_gold if self.n_gold else None

    @property
    def precision(self) -> float | None:
        return self.n_match / self.n_pred if self.n_pred else None


@dataclass
class ReadScore:
    pdf_id: str
    kinds: dict[str, KindScore] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pdf_id": self.pdf_id,
            "kinds": {
                k: {
                    "n_gold": s.n_gold,
                    "n_pred": s.n_pred,
                    "n_match": s.n_match,
                    "recall": s.recall,
                    "precision": s.precision,
                }
                for k, s in self.kinds.items()
            },
        }


def layout_path(cfg, eval_root: Path, pdf_id: str) -> Path:
    """PDF の layout.json の場所（コーパス設定の paths.gold のうち layout.json のひな型から）。"""
    tpl = [t for t in cfg.paths.gold if t.endswith("/layout.json")]
    if len(tpl) != 1:
        raise ReadScoreError("コーパス設定の paths.gold に layout.json のひな型が 1 つだけ要る")
    doc_id, sep, style = pdf_id.partition("--")
    if not (sep and doc_id and style):
        raise ReadScoreError(f"PDF ID は <文書 ID>--<体裁> の形でなければならない: {pdf_id}")
    rel = render(tpl[0], doc_id=doc_id).replace(f"{doc_id}--*", pdf_id)
    if "*" in rel:
        raise ReadScoreError(f"layout.json のひな型を PDF に解決できない: {tpl[0]}")
    return eval_root / rel


def _boxes_by_page(srcs: Iterable[dict]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for s in srcs:
        b = s.get("bbox")
        if not b or s.get("page") is None:
            continue
        p = int(s["page"])
        u = out.get(p)
        out[p] = (
            list(b)
            if u is None
            else [min(u[0], b[0]), min(u[1], b[1]), max(u[2], b[2]), max(u[3], b[3])]
        )
    return out


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    area = lambda x: max(0.0, x[2] - x[0]) * max(0.0, x[3] - x[1])  # noqa: E731
    small = min(area(a), area(b))
    return (w * h) / small if small > 0 else 0.0


def pdoc_units(doc: dict) -> dict[str, list[dict[int, list[float]]]]:
    """pdoc の単位を種類ごとに（ページ → 和の bbox）で返す。"""
    out: dict[str, list[dict[int, list[float]]]] = defaultdict(list)

    def blocks(bs):
        for b in bs:
            t = b.get("type")
            if t in ("table", "formula", "figure"):
                bb = b.get("bbox")
                if bb and b.get("page") is not None:
                    out[t].append({int(b["page"]): list(bb)})
                else:
                    out[t].append(_boxes_by_page(b.get("src", [])))
            blocks(b.get("blocks", []))

    def walk(ns):
        for n in ns:
            k = n.get("kind")
            if k in ("chapter", "article", "paragraph", "item"):
                out[k].append(_boxes_by_page(n.get("src", [])))
            blocks(n.get("blocks", []))
            walk(n.get("children", []))

    walk(doc.get("body", []) + doc.get("front_matter", []) + doc.get("appendices", []))
    return out


def gold_units(layout: dict) -> dict[str, list[dict[int, list[float]]]]:
    out: dict[str, list[dict[int, list[float]]]] = defaultdict(list)
    for e in layout.get("elements", {}).values():
        k = KINDS.get(e.get("kind"))
        if k is None:
            continue
        frags = [f for f in e.get("fragments", []) if not f.get("repeated")]
        out[k].append(_boxes_by_page(frags))
    return out


def _match(gold: list[dict], pred: list[dict]) -> int:
    pairs = []
    for i, g in enumerate(gold):
        for j, p in enumerate(pred):
            best = max((_overlap_ratio(gb, p[pg]) for pg, gb in g.items() if pg in p), default=0.0)
            if best >= MIN_OVERLAP:
                pairs.append((best, i, j))
    used_g, used_p, n = set(), set(), 0
    for _, i, j in sorted(pairs, key=lambda x: (-x[0], x[1], x[2])):
        if i in used_g or j in used_p:
            continue
        used_g.add(i)
        used_p.add(j)
        n += 1
    return n


def score(pdf_id: str, doc: dict, layout: dict) -> ReadScore:
    style = pdf_id.partition("--")[2]
    if layout.get("style_id") and style and layout["style_id"] != style:
        raise ReadScoreError(
            f"layout.json の体裁 {layout['style_id']} と PDF の体裁 {style} が違う（採点しない）"
        )
    g, p = gold_units(layout), pdoc_units(doc)
    rs = ReadScore(pdf_id)
    for k in dict.fromkeys(KINDS.values()):
        rs.kinds[k] = KindScore(
            len(g.get(k, [])), len(p.get(k, [])), _match(g.get(k, []), p.get(k, []))
        )
    gb = [u for k in BODY_KINDS for u in g.get(k, [])]
    pb = [u for k in BODY_KINDS for u in p.get(k, [])]
    rs.kinds["body"] = KindScore(len(gb), len(pb), _match(gb, pb))
    return rs


def score_files(cfg, eval_root: Path, pdoc_dir: Path, pdf_ids: Iterable[str]) -> list[ReadScore]:
    out = []
    for pid in pdf_ids:
        lp = layout_path(cfg, eval_root, pid)
        if not lp.is_file():
            raise ReadScoreError(
                f"layout.json がありません: {lp}（jpcalc fetch-gold で取得してください）"
            )
        dp = pdoc_dir / f"{pid}.json"
        if not dp.is_file():
            raise ReadScoreError(f"pdoc がありません: {dp}（jpcalc pdoc で作ってください）")
        out.append(
            score(
                pid,
                json.loads(dp.read_text(encoding="utf-8")),
                json.loads(lp.read_text(encoding="utf-8")),
            )
        )
    return out


def total(scores: Iterable[ReadScore]) -> dict[str, KindScore]:
    t: dict[str, KindScore] = {}
    for s in scores:
        for k, v in s.kinds.items():
            a = t.setdefault(k, KindScore())
            a.n_gold += v.n_gold
            a.n_pred += v.n_pred
            a.n_match += v.n_match
    return t

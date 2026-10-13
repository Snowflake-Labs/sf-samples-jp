"""当事者と定義語の採点（F6・T6.2・C-007）。採点側専用（`read/` から import しない）。

当事者
  gold : `source.json` の `meta.parties[]` の (alias, name)
  pred : 出力 JSON の `parties[]` の (alias, name)
  比較 : NFKC＋空白除去で正規化した対の集合の P / R / F1。
         呼称の取り違え（同じ名称に違う呼称）を `n_alias_swapped` として別に数える。
定義語
  gold : `source.json` の `defined_terms[].term`
  pred : 出力 JSON の `defined_terms`（語の配列）
  比較 : 正規化した語の集合の P / R / F1。gold に定義語の無い文書は採点から外す（`n_gold == 0`）。

指標の式は単純な集合 F1 で、約款の採点（metrics_*.py）は変えない（新しい軸は新しいモジュールに足す）。
"""

from __future__ import annotations

import re
import unicodedata

from .gold import load_source


def _norm(s: str) -> str:
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", s or ""))


def _prf(gold: set, pred: set) -> dict:
    tp = len(gold & pred)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {
        "n_gold": len(gold),
        "n_pred": len(pred),
        "tp": tp,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f, 4),
    }


def party_scores(doc_id: str, pred: dict) -> dict:
    gold_pairs = {
        (_norm(p["alias"]), _norm(p["name"]))
        for p in load_source(doc_id)["meta"].get("parties") or []
    }
    pred_pairs = {(_norm(p.get("alias")), _norm(p.get("name"))) for p in pred.get("parties") or []}
    out = _prf(gold_pairs, pred_pairs)
    gname = {n: a for a, n in gold_pairs}
    out["n_alias_swapped"] = sum(1 for a, n in pred_pairs if n in gname and gname[n] != a)
    return out


def term_scores(doc_id: str, pred: dict) -> dict:
    gold = {_norm(t["term"]) for t in load_source(doc_id).get("defined_terms") or []}
    predset = {_norm(t) for t in pred.get("defined_terms") or [] if t}
    return _prf(gold, predset)


def summarize(rows: list[dict]) -> dict:
    """文書ごとの tp/n_gold/n_pred を足し合わせた（ミクロ）P/R/F1。gold 0 件の文書は除く。"""
    rs = [r for r in rows if r and r["n_gold"]]
    tp = sum(r["tp"] for r in rs)
    g = sum(r["n_gold"] for r in rs)
    p = sum(r["n_pred"] for r in rs)
    pr, rc = (tp / p if p else 0.0), (tp / g if g else 0.0)
    out = {
        "n_docs": len(rs),
        "n_gold": g,
        "n_pred": p,
        "tp": tp,
        "precision": round(pr, 4),
        "recall": round(rc, 4),
        "f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0,
    }
    if rs and "n_alias_swapped" in rs[0]:
        out["n_alias_swapped"] = sum(r["n_alias_swapped"] for r in rs)
    return out

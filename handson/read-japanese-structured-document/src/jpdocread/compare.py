"""出力 JSON の決定的な層の比較。

AI を使わない層（条項木・引用・参照・表・脚注・列挙・当事者・定義語）は PDF のテキスト層と LAYOUT の生 Markdown
だけから決まるので、同じ入力なら移植元と完全に一致するはずである。本文 pages と図は AI の出力そのものなので比べない。

`term_uses` だけは**多重集合として**比べる。移植元の `semantics.term_uses` は同じ長さの定義語の順序が
集合の反復順（文字列ハッシュの乱数種）で変わり、移植元の run どうしでも並びが一致しないため。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

EXACT_KEYS: tuple[str, ...] = (
    "outline",
    "elements",
    "refs",
    "tables",
    "footnotes",
    "enumerations",
    "defined_terms",
    "numbering_scheme",
    "parties",
    "defined_terms_detail",
)
MULTISET_KEYS: tuple[str, ...] = ("term_uses",)


def _multiset(items: Iterable) -> list[str]:
    return sorted(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in items or [])


def diff_keys(a: dict, b: dict) -> list[str]:
    """2 つの出力 JSON で一致しないキーを返す。片方にしか無いキーは不一致（`None` と空配列は区別する）。"""
    bad = [k for k in EXACT_KEYS if (k in a) != (k in b) or a.get(k) != b.get(k)]
    bad += [k for k in MULTISET_KEYS if _multiset(a.get(k)) != _multiset(b.get(k))]
    return bad


def compare_dirs(
    a: Path, b: Path, doc_ids: Iterable[str], *, ignore_missing_keys: Iterable[str] = ()
) -> dict:
    """doc_ids の各文書について a/<doc>.json と b/<doc>.json を比べる。

    `ignore_missing_keys` は、片方（移植元）に無いキーを比べないための指定。約款の移植元は契約書の追加キー
    （numbering_scheme・parties・defined_terms_detail）を出さないので、約款の照合ではこれを渡す。
    """
    ignore = set(ignore_missing_keys)
    result: dict[str, list[str]] = {}
    for d in doc_ids:
        pa, pb = a / f"{d}.json", b / f"{d}.json"
        if not pa.exists() or not pb.exists():
            result[d] = ["片方にしか無い"]
            continue
        x = json.loads(pa.read_text(encoding="utf-8"))
        y = json.loads(pb.read_text(encoding="utf-8"))
        for k in ignore:
            if k not in x or k not in y:
                x.pop(k, None)
                y.pop(k, None)
        bad = diff_keys(x, y)
        if bad:
            result[d] = bad
    return result


def metric_diffs(mine: Any, ref: Any, path: str = "") -> dict[str, list[str]]:
    """採点結果（文書別の指標）を値で比べる（移植元の DOC_METRICS との照合）。

    - 数値は値で比べる（`0` と `0.0` を同じとみなす）。移植元の値は Snowflake の VARIANT を通って
      `1.0` が `1` に正規化されているため、JSON の文字列としては比べない。
    - 片方にしか無いキーは不一致にせず、`only_mine`・`only_ref` に分けて返す。約款の移植元の採点は
      契約書の移植元で足された指標（網羅率 coverage・n_gold・n_matched・nted_doc）を出さないため。
    戻り値：{"value": [値が違うパス], "only_mine": [...], "only_ref": [...]}。
    """
    out: dict[str, list[str]] = {"value": [], "only_mine": [], "only_ref": []}
    if isinstance(mine, dict) and isinstance(ref, dict):
        for k in sorted(set(mine) | set(ref)):
            p = f"{path}/{k}"
            if k not in ref:
                out["only_mine"].append(p)
            elif k not in mine:
                out["only_ref"].append(p)
            else:
                for kind, items in metric_diffs(mine[k], ref[k], p).items():
                    out[kind].extend(items)
    elif mine != ref:
        out["value"].append(path or "/")
    return out


# 文書単位で移植元と完全一致するはずの指標（テキスト層だけから決まる）。
# 本文（text）・表・図は AI 関数の揺れを受けるので、差を記録するだけで一致を要求しない
STRUCTURAL_METRICS = ("citation", "structure", "refs", "parties", "terms", "numbering_scheme")
AI_METRICS = ("text",)


def compare_doc_metrics(mine: dict[str, dict], ref: dict[str, dict]) -> dict:
    """文書別の指標（doc_id → payload.metrics）を移植元と比べる。共通の文書だけを比べる。

    比較先に無い指標の群は比べない（約款の移植元の採点は parties・terms を出さない）。
    比較先にある群が本実装に無ければ不一致にする（黙って比べないことにしない）。
    """
    common = sorted(set(mine) & set(ref))
    per_doc = {}
    for d in common:
        fam = [k for k in STRUCTURAL_METRICS if k in ref[d]]
        structural = [p for k in fam for p in metric_diffs(mine[d].get(k), ref[d][k], k)["value"]]
        ai = [
            p
            for k in AI_METRICS
            if k in ref[d]
            for p in metric_diffs(mine[d].get(k), ref[d][k], k)["value"]
        ]
        per_doc[d] = {
            "compared": fam,
            "not_in_ref": [k for k in STRUCTURAL_METRICS if k not in ref[d]],
            "structural_mismatch": structural,
            "ai_differences": ai,
        }
    return {
        "n_compared": len(common),
        "missing_in_ref": sorted(set(mine) - set(ref)),
        "n_structural_mismatch": sum(1 for v in per_doc.values() if v["structural_mismatch"]),
        "docs": per_doc,
    }

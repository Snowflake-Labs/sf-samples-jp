"""T 段の層 2：設例（文書に印刷された支払例）をテストケースに構造化する。

LLM には値を表記のまま書き写させ、金額・日付・日数は数値パーサで確定させる（LLM に計算させない）。
解析できない設例はエラーとして記録し、テストに使わない（黙って落とさないが、誤った期待値も作らない）。
"""

from __future__ import annotations

import json

from ..common import numparse as N
from ..common.paths import CONFIGS
from .d_spec import card_view
from .llm import Req
from .policy_index import PolicyIndex

PROMPT_VERSION = "t_examples_p1"


def example_paragraphs(ix: PolicyIndex, containers: list[str]) -> list[tuple[str, str]]:
    out = []
    for c in containers:
        for oid in ix.order:
            n = ix.by_id[oid]
            if (
                (oid == c or c in ix.ancestors(oid))
                and n.get("type") == "box"
                and oid.endswith("_note")
            ):
                for b in n.get("blocks", []):
                    if b.get("type") == "paragraph":
                        out.append((b["id"], ix.expand(b.get("text"))))
    return out


def make_request(
    doc_id: str, paras: list[tuple[str, str]], cards: list[dict], *, model: str, max_tokens: int
) -> Req | None:
    if not paras:
        return None
    t = (CONFIGS / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
    t = t.replace("<<EXAMPLES>>", "\n".join(f"[{i}] {s}" for i, s in paras))
    t = t.replace(
        "<<CARDS>>", json.dumps([card_view(c) for c in cards], ensure_ascii=False, indent=1)
    )
    return Req(
        stage="T_examples",
        doc_id=doc_id,
        unit="+".join(c["function"] for c in cards),
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=PROMPT_VERSION,
        model=model,
    )


def _val(v, typ: str, fields=None):
    if v is None:
        return None
    if typ == "bool":
        if isinstance(v, bool):
            return v
        raise ValueError(f"bool expected: {v!r}")
    if typ == "date":
        return N.parse_date(str(v)).isoformat()
    if typ == "list":
        fmap = {f["name"]: f["type"] for f in fields or []}
        return [{k: _val(x, fmap.get(k, "int")) for k, x in it.items()} for it in v]
    if isinstance(v, bool):
        raise ValueError(f"int expected: {v!r}")
    if isinstance(v, int):
        return v
    q = N.parse(str(v))
    if not isinstance(q.value, int):
        raise ValueError(f"non-integer {v!r}")
    return q.value


def to_cases(parsed: dict, cards: list[dict]) -> tuple[list[dict], list[str]]:
    cmap = {c["function"]: c for c in cards}
    cases, errs = [], []
    for ex in (parsed or {}).get("examples", []):
        fn = ex.get("function")
        c = cmap.get(fn)
        if c is None:
            errs.append(f"unknown function {fn!r} in example {ex.get('source')}")
            continue
        try:
            ins = {}
            for i in c["inputs"]:
                ins[i["name"]] = _val(
                    (ex.get("inputs") or {}).get(i["name"]), i["type"], i.get("fields")
                )
            exp = _val(ex.get("expected"), c["output"]["type"])
        except (N.NumParseError, ValueError, TypeError, AttributeError) as e:
            errs.append(f"{ex.get('source')}:{fn}: {e}")
            continue
        cases.append(
            {
                "kind": "example",
                "source": ex.get("source"),
                "function": fn,
                "inputs": ins,
                "expected": exp,
            }
        )
    return cases, errs

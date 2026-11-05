"""R 段：自己テストの失敗から計算仕様を直す（正解は見ない）。

入力は自己テストの結果（T の出力）と約款の文脈だけで、正解のケースや正解仕様は使わない。
直す先：設例・仕様の形・仕様の例外・性質の失敗 → D（LLM で仕様を直す）。
インタプリタと生成コードの不一致 → I（生成器の誤り。LLM では直さず記録する）。
"""

from __future__ import annotations

import json

from . import d_spec
from .d_spec import render_problem
from .llm import Req
from .prompts import template

PROMPT_VERSION = "r_repair_p1"
D_LAYERS = {"example", "crosscheck", "check", "spec_error", "property", "static"}


def needs_d_repair(fails: list[dict]) -> bool:
    return any(f["layer"] in D_LAYERS for f in fails)


def _rules_section() -> str:
    t = template(d_spec.PROMPT_VERSION)  # D の雛形の「出力の形」の節を使い回す
    a = t.index("# 出力の形")
    b = t.index("# 例")
    return t[a:b].strip()


def make_request(
    doc_id: str,
    ctx: dict,
    cards: list[dict],
    previous: dict,
    fails: list[dict],
    *,
    model: str,
    max_tokens: int,
    iteration: int,
) -> Req:
    pr = render_problem(ctx, cards)
    t = template(PROMPT_VERSION)
    t = t.replace("<<RULES>>", _rules_section())
    for k, v in pr.items():
        t = t.replace(f"<<{k}>>", v)
    t = t.replace("<<PREVIOUS>>", json.dumps(previous, ensure_ascii=False))
    t = t.replace("<<FAILURES>>", json.dumps(fails, ensure_ascii=False, default=str, indent=1))
    return Req(
        stage=f"R{iteration}",
        doc_id=doc_id,
        unit="+".join(c["function"] for c in cards),
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=PROMPT_VERSION,
        model=model,
    )

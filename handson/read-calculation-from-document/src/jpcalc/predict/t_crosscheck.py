"""T 段の層 4：独立の検算（記録だけ。改修や最終版の選択には使わない）。

仕様を見せずに、LLM に約款の文言だけで答えを計算させ、生成コードの答えと比べる。
入力は仕様から作るテストのうち「仕様の判断が分かれやすい点」（比較の境界・端数処理・限度・条件）を選ぶ。
LLM の計算は誤ることがあるので、不一致は「疑い」として改修に渡し、改修側でも約款の文言で判断させる
（検算の答えに合わせることを強制しない）。
"""

from __future__ import annotations

import json

from ..common.paths import CONFIGS
from . import casegen
from .d_spec import card_view
from .llm import Req

PROMPT_VERSION = "t_crosscheck_p1"


def pick_cases(
    spec: dict, cards: list[dict], *, per_function: int = 4, seed: int = 7
) -> list[dict]:
    """関数ごとに境界の入力から per_function 件（不明の入力は含めない。検算の負担を減らす）。"""
    import random

    rng = random.Random(seed)
    cmap = {c["function"]: c for c in cards}
    out = []
    for r in spec["rules"]:
        c = cmap.get(r["function"])
        if c is None or any(i["type"] == "list" for i in c["inputs"]):
            continue
        cs = [
            x
            for x in casegen.generate(spec, r, c, n_random=20, seed=seed)
            if x["kind"] == "boundary"
        ]
        cs = [x for x in cs if all(v is not None for v in x["inputs"].values())]
        rng.shuffle(cs)
        for x in cs[:per_function]:
            out.append({"function": r["function"], "inputs": casegen.to_json_inputs(x["inputs"])})
    return out


def make_request(
    doc_id: str, ctx: dict, cards: list[dict], cases: list[dict], *, model: str, max_tokens: int
) -> Req | None:
    if not cases:
        return None
    t = (CONFIGS / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
    t = t.replace("<<CONTEXT>>", ctx["text"])
    t = t.replace(
        "<<CARDS>>", json.dumps([card_view(c) for c in cards], ensure_ascii=False, indent=1)
    )
    t = t.replace(
        "<<CASES>>",
        "\n".join(
            f"{i}. {c['function']}({json.dumps(c['inputs'], ensure_ascii=False)})"
            for i, c in enumerate(cases, 1)
        ),
    )
    return Req(
        stage="T_cross",
        doc_id=doc_id,
        unit="cross",
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=PROMPT_VERSION,
        model=model,
    )


def to_examples(parsed: dict, cases: list[dict], cards: list[dict]) -> list[dict]:
    """検算の答え → 層 2 と同じ形の「検算例」（kind=crosscheck）。読めない答えは捨てる。"""
    cmap = {c["function"]: c for c in cards}
    out = []
    for a in (parsed or {}).get("results", []):
        try:
            i = int(a.get("id")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= i < len(cases):
            continue
        c = cases[i]
        typ = cmap[c["function"]]["output"]["type"]
        v = a.get("answer")
        if typ == "bool" and not isinstance(v, bool | type(None)):
            continue
        if typ == "int" and not (v is None or (isinstance(v, int) and not isinstance(v, bool))):
            continue
        if typ == "date" and not (v is None or isinstance(v, str)):
            continue
        out.append(
            {
                "kind": "crosscheck",
                "source": f"crosscheck#{i + 1}",
                "function": c["function"],
                "inputs": c["inputs"],
                "expected": v,
                "work": a.get("work"),
            }
        )
    return out

"""D 段：規定 → 計算仕様。

1 文書 1 回の LLM 呼び出しで、その文書のタスクカードの関数すべての式の木を組ませる（関数どうしの呼び出しがあるため）。
LLM には定数のキーと表ブロックの id だけを参照させ、値は context が決定的に解決したものを後処理で入れる。
出力は spec.check で検証し、問題はエラーとして残す（黙って直さない）。
"""

from __future__ import annotations

import json
import re

from ..common.paths import CONFIGS, WORK
from . import context as CTX
from . import spec as SP
from .llm import Req
from .policy_index import PolicyIndex

PROMPT_VERSION = "d_spec_p1"


def card_view(c: dict) -> dict:
    out = {
        "function": c["function"],
        "kind": c["kind"],
        **({"title": c["title"]} if c.get("title") else {}),
        "inputs": [
            {k: i[k] for k in ("name", "type", "unit", "desc", "origin", "exclusion") if k in i}
            | (
                {
                    "fields": [
                        {k: f[k] for k in ("name", "type", "unit", "desc") if k in f}
                        for f in i["fields"]
                    ]
                }
                if i.get("fields")
                else {}
            )
            for i in c["inputs"]
        ],
        "output": c["output"]["type"],
    }
    return out


def render_problem(ctx: dict, cards: list[dict]) -> dict:
    consts = {
        k: {"表記": v["text"], "値": v["value"], "単位": v["unit"]}
        | ({"注意": v["error"]} if v.get("error") else {})
        for k, v in ctx["constants"].items()
    }
    tables = {
        k: (v["rows"] if v.get("rows") is not None else f"読み取れない: {v.get('error')}")
        for k, v in ctx["tables"].items()
    }
    return {
        "CONTEXT": ctx["text"],
        "CONSTANTS": json.dumps(consts, ensure_ascii=False, indent=1),
        "TABLES": json.dumps(tables, ensure_ascii=False),
        "CARDS": json.dumps([card_view(c) for c in cards], ensure_ascii=False, indent=1),
    }


def load_shots(version: str = "v1") -> list[dict]:
    p = WORK / "shots" / f"d_spec_{version}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def render_shots(shots: list[dict]) -> str:
    out = []
    for i, s in enumerate(shots, 1):
        pr = s["problem"]
        out.append(
            f"## 例{i}：入力\n### 約款の該当箇所\n{pr['CONTEXT']}\n### 定数一覧\n{pr['CONSTANTS']}\n"
            f"### 表の読み取り結果\n{pr['TABLES']}\n### 実装する関数の宣言\n{pr['CARDS']}\n"
            f"## 例{i}：出力\n{json.dumps(s['answer'], ensure_ascii=False)}\n"
        )
    return "\n".join(out)


def build_prompt(problem: dict, shots_text: str, version: str = PROMPT_VERSION) -> str:
    t = (CONFIGS / "prompts" / f"{version}.txt").read_text(encoding="utf-8")
    t = t.replace("<<SHOTS>>", shots_text)
    for k, v in problem.items():
        t = t.replace(f"<<{k}>>", v)
    return t


def make_request(
    doc_id: str,
    ctx: dict,
    cards: list[dict],
    *,
    model: str,
    max_tokens: int,
    shots_text: str,
    version: str = PROMPT_VERSION,
) -> Req:
    prompt = build_prompt(render_problem(ctx, cards), shots_text, version)
    return Req(
        stage="D",
        doc_id=doc_id,
        unit="+".join(c["function"] for c in cards),
        prompt=prompt,
        max_tokens=max_tokens,
        prompt_version=version,
        model=model,
    )


def assemble(doc_id: str, answer: dict, ctx: dict, cards: list[dict]) -> tuple[dict, list[str]]:
    """LLM の出力（rules だけ）→ 計算仕様 v1。定数と表を解決し、検証の問題を返す。"""
    probs: list[str] = []
    cardmap = {c["function"]: c for c in cards}
    params: dict = {}
    where = {"fn": None}
    tables: dict = {}
    rules = []

    def fix(e):
        if isinstance(e, list):
            return [fix(x) for x in e]
        if not isinstance(e, dict):
            return e
        e = dict(e)
        if "param" in e and "op" not in e:
            k = e["param"]
            c = ctx["constants"].get(k) or (ctx.get("all_constants") or {}).get(k)
            if c is None:
                probs.append(f"{where['fn']}: unknown constant {k!r}")
            elif c.get("value") is None:
                probs.append(f"{where['fn']}: constant {k!r} unresolved: {c.get('error')}")
            else:
                params[k] = {
                    "value": c["value"],
                    "unit": c["unit"],
                    "const_key": k,
                    "text": c["text"],
                }
        if e.get("op") == "lookup":
            bid, mode = e.get("table"), e.pop("mode", "exact")
            t = ctx["tables"].get(bid)
            if t is None or t.get("rows") is None:
                probs.append(
                    f"{where['fn']}: table {bid!r} not readable (表ブロックが文脈に無いか、数値の表でない)"
                )
            else:
                name = f"{bid}__{mode}"
                tables[name] = {
                    "rows": t["rows"],
                    "mode": mode if mode in ("exact", "step_le", "step_ge") else "exact",
                    "block_id": bid,
                }
                e["table"] = name
        if "args" in e:
            e["args"] = fix(e["args"])
        return e

    for r in (answer or {}).get("rules", []):
        fn = r.get("function")
        if fn not in cardmap:
            probs.append(f"unexpected function {fn!r}")
            continue
        c = cardmap[fn]
        where["fn"] = fn
        rules.append(
            {
                "function": fn,
                "kind": r.get("kind") or c["kind"],
                "title": c.get("title"),
                "output_type": c["output"]["type"],
                "inputs": [
                    {
                        k: v
                        for k, v in i.items()
                        if k in ("name", "type", "fields", "min", "max", "max_items", "exclusion")
                    }
                    for i in c["inputs"]
                ],
                "steps": [
                    {"name": s.get("name"), "label": s.get("label"), "expr": fix(s.get("expr"))}
                    for s in r.get("steps", [])
                ],
                "output": r.get("output"),
                "explicit": _explicit(r.get("explicit")),
                "unresolved": r.get("unresolved") or [],
                "evidence_units": ctx.get("units", []),
            }
        )
    spec = {
        "spec_version": "jpcalc-1",
        "doc_id": doc_id,
        "params": params,
        "tables": tables,
        "rules": rules,
    }
    probs += SP.check(spec, cards)
    return spec, probs


def _explicit(v):
    """explicit は一義性の記録で、生成・計算には使わない。注記の文字列の列で返ったときは {"notes": [...]} に入れる
    （形の揺れ 1 つで関数が仕様の検査に落ちないように。内容は変えない）。それ以外の形はそのまま検査に回す。"""
    if v is None:
        return {}
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return {"notes": v}
    if isinstance(v, str):
        return {"notes": [v]}
    return v


def usable_subset(spec: dict, cards: list[dict], probs: list[str]) -> tuple[dict | None, list[str]]:
    """問題のある関数（とそれを呼ぶ関数）を外した仕様。問題の無い関数だけで生成・自己テストを続ける。

    1 つの関数の誤りで文書全体のモジュールが作れなくなるのを防ぐ（1 関数の誤りで 6 ルールを失った例があった）。
    外した関数は不合格のまま残り、問題は改修（R）に渡す。
    """
    fns = [r["function"] for r in spec.get("rules", [])]

    def owners(p: str) -> set[str]:
        return {f for f in fns if p.startswith(f"{f}:") or p.startswith(f"{f}.") or f" {f}:" in p}

    bad = {f for p in probs for f in owners(p)}
    # 関数に帰属しない問題：名前の挙がった定数・表を参照する関数と、呼び出しの循環に入る関数を外す。
    # 拾う語は仕様の定数と表のキー（と値スパンの形 vNNN）だけにする。スキーマの文の語（'name' など）で
    # 健全な関数まで外さないため
    keys = set(spec.get("params") or {}) | set(spec.get("tables") or {})
    broken: set[str] = set()  # 帰属しない問題で名前の挙がった定数・表（部分集合からも除く）
    for p in probs:
        if owners(p):
            continue
        words = re.findall(r"'([^']+)'", p) + re.findall(r"^(?:param|table)s? (\S+?):", p)
        toks = {t for t in words if t in keys or re.fullmatch(r"v\d+", t)}
        broken |= toks
        if m := re.match(r"rule cycle via (\S+) -> (\S+)", p):
            bad.update(x for x in m.groups() if x in fns)
        for r in spec.get("rules", []):
            blob = json.dumps(r["steps"], ensure_ascii=False)
            # 表は名前のまま（読めない表）か「名前__照合の方法」で参照される
            if any(
                f'"param": "{t}"' in blob or f'"table": "{t}"' in blob or f'"table": "{t}__' in blob
                for t in toks
            ):
                bad.add(r["function"])
    changed = True
    while changed:
        changed = False
        for r in spec.get("rules", []):
            if r["function"] in bad:
                continue
            blob = json.dumps(r["steps"], ensure_ascii=False)
            if any(f'"rule": "{b}"' in blob for b in bad):
                bad.add(r["function"])
                changed = True
    keep = [r for r in spec.get("rules", []) if r["function"] not in bad]
    if not keep:
        return None, sorted(bad)
    # 外した関数だけが参照していた壊れた定数・表は、残す関数は参照しないので仕様から除く
    sub = dict(
        spec,
        rules=keep,
        params={k: v for k, v in (spec.get("params") or {}).items() if k not in broken},
        tables={k: v for k, v in (spec.get("tables") or {}).items() if k not in broken},
    )
    sub_cards = [c for c in cards if c["function"] in {r["function"] for r in keep}]
    if SP.check(sub, sub_cards):
        return None, sorted(bad)
    return sub, sorted(bad)


def doc_context(ix: PolicyIndex, units: list[str]) -> dict:
    ctx = CTX.build(ix, units)
    ctx["units"] = units
    # 定数は文書全体で一意のキーなので、文脈の外の条で定義されたものも決定的に解決できる（プロンプトには載せない）
    ctx["all_constants"] = {k: CTX.resolve_const(v) for k, v in ix.constants.items()}
    return ctx

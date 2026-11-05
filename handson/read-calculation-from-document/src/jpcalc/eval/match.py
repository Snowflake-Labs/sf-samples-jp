"""対応付け M とアダプタ（評価側だけ）。

正解の pytest は正解の関数名・引数名で呼ぶ。生成物は PDF から合成したカードの名前なので、
(1) 生成した関数 ↔ 正解のルール、(2) 生成した引数 ↔ 正解の引数 を決定的に対応付け、
正解の名前で呼ばれたら生成した関数へ引数を写して渡すモジュール（アダプタ）を作る。

M が読むもの：正解のカード（題名・種別・入出力の型と単位・説明）・answer_key（根拠の単位）・根拠の本文の JSON、
生成の合成カード（cards.jsonl。根拠の本文 evidence_text を持つ）。**テストケース・期待値・採点結果は読まない。**

規則：
  - 関数の候補は種別（kind）と出力の型が一致するものだけ。契約書の determination は decision と同じに扱う
  - 点数 = 根拠の本文の文字 n-gram の重なり × 0.6 + 題名の類似 × 0.4。総合点と根拠の重なりに下限を置く
  - 点数の高い順に 1 対 1 で対応させる（同点は名前の順）
  - 生成側にだけある引数へ値を補わない（主指標）。補った値は診断だけに使う
"""

from __future__ import annotations

import json
import re
import unicodedata

from ..predict.k_cards import unit_text
from ..predict.policy_index import PolicyIndex

# 関数の対応の重みと閾値（移植元で決めて凍結した値。採点結果を見て変えない）
W_EVIDENCE, W_TITLE, THRESHOLD = 0.6, 0.4, 0.30
# 根拠の本文の重なりの下限（題名の決まり文句「〜の支払の判定」だけで別の規定に対応しないように）
MIN_EVIDENCE = 0.40
_ASCII = re.compile(r"[A-Za-z]+")  # 表の書式情報（header・center など）を比較から除く
_STRIP = re.compile(r"[\s　、。・，．,.:：;；()（）「」『』\[\]【】{}＝=＋+－\-×÷/／]")
CALENDAR_ARG = "holidays"  # 営業日を扱う関数の予約引数（呼び出し規約）


def _norm(s: str) -> str:
    return _STRIP.sub("", _ASCII.sub("", unicodedata.normalize("NFKC", s or "")))


def grams(s: str, n: int) -> set[str]:
    s = _norm(s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def dice(a: str, b: str, n: int = 2) -> float:
    A, B = grams(a, n), grams(b, n)
    return 2 * len(A & B) / (len(A) + len(B)) if A and B else 0.0


def containment(gold_text: str, pred_text: str, n: int = 3) -> float:
    G, P = grams(gold_text, n), grams(pred_text, n)
    return len(G & P) / len(G) if G else 0.0


def norm_kind(k: str | None) -> str:
    return "decision" if k in ("decision", "determination") else (k or "")


def _out_type(c: dict) -> str | None:
    o = c.get("output")
    return o.get("type") if isinstance(o, dict) else o


def evidence_overlap(gold_units: list[str], pred_text: str) -> float:
    """正解の根拠全体の包含率と、正解の単位ごとの包含率の最大の大きい方。

    予測が正解の根拠単位を 1 つでも同じ本文で選んでいれば同じ規定とみなす（表を選ばなかった場合など）。
    """
    whole = containment(" ".join(gold_units), pred_text)
    per = max(
        (containment(u, pred_text) for u in gold_units if len(_norm(u)) >= 12),
        default=0.0,
    )
    return max(whole, per)


def match_functions(
    gold_cards: list[dict],
    gold_text: dict[str, list[str]],
    gen_cards: list[dict],
    gen_text: dict[str, str],
) -> tuple[dict[str, str], list[dict]]:
    """正解の関数 → 生成の関数（1 対 1・貪欲）。"""
    pairs = []
    for g in gold_cards:
        for p in gen_cards:
            if norm_kind(g.get("kind")) != norm_kind(p.get("kind")) or _out_type(g) != _out_type(p):
                continue
            ev = evidence_overlap(gold_text[g["function"]], gen_text[p["function"]])
            ti = dice(g.get("title", ""), p.get("title", ""))
            pairs.append((W_EVIDENCE * ev + W_TITLE * ti, ev, ti, g["function"], p["function"]))
    pairs.sort(key=lambda x: (-x[0], x[3], x[4]))
    fmap: dict[str, str] = {}
    used: set[str] = set()
    detail = []
    for sc, ev, ti, gf, pf in pairs:
        if sc < THRESHOLD or ev < MIN_EVIDENCE or gf in fmap or pf in used:
            continue
        fmap[gf] = pf
        used.add(pf)
        detail.append(
            {
                "gold": gf,
                "gen": pf,
                "score": round(sc, 3),
                "evidence": round(ev, 3),
                "title": round(ti, 3),
            }
            | evidence_diagnostics(gold_text[gf], gen_text[pf])
        )
    return fmap, detail


def evidence_diagnostics(gold_units: list[str], pred_text: str) -> dict:
    """診断だけの値（対応付けの判定には使わない）。根拠の重なりは正解から見た包含なので、生成の根拠が
    長いほど上がる。その偏りを見るために、生成から見た重なりと、長さの比を残す。"""
    gold = " ".join(gold_units)
    n_gold = len(_norm(gold))
    return {
        "gen_precision": round(containment(pred_text, gold), 3),
        "length_ratio": round(len(_norm(pred_text)) / n_gold, 3) if n_gold else None,
    }


def _compatible(g: dict, p: dict) -> bool:
    if g.get("type") != p.get("type"):
        return False
    return g.get("type") != "int" or g.get("unit") == p.get("unit")


def _arg_score(g: dict, p: dict) -> float:
    return dice(g.get("desc", ""), p.get("desc", "")) + 0.3 * dice(
        g["name"].replace("_", " "), p["name"].replace("_", " ")
    )


def match_args(
    g_inputs: list[dict], p_inputs: list[dict]
) -> tuple[dict[str, str], dict[str, dict[str, str]], int]:
    """正解の引数 → 生成の引数（型と単位が合うものの中で、説明と名前の類似が最大の 1 対 1）。

    戻り値：(引数の写像, list の fields の写像, 曖昧だった正解の引数の数)。
    """
    pairs = sorted(
        (
            (_arg_score(g, p), g["name"], p["name"])
            for g in g_inputs
            for p in p_inputs
            if _compatible(g, p)
        ),
        key=lambda x: (-x[0], x[1], x[2]),
    )
    amap: dict[str, str] = {}
    used: set[str] = set()
    for _, gn, pn in pairs:
        if gn in amap or pn in used:
            continue
        amap[gn] = pn
        used.add(pn)
    ambiguous = sum(1 for g in g_inputs if sum(_compatible(g, p) for p in p_inputs) > 1)
    gi = {i["name"]: i for i in g_inputs}
    pi = {i["name"]: i for i in p_inputs}
    fmaps = {}
    for gn, pn in amap.items():
        if gi[gn]["type"] == "list":
            fm, _, _ = match_args(gi[gn].get("fields") or [], pi[pn].get("fields") or [])
            fmaps[gn] = fm
    return amap, fmaps, ambiguous


def gold_evidence(
    gold_cards: list[dict], answer_key: list[dict], text_json: dict
) -> dict[str, list[str]]:
    """正解の関数 → 根拠の単位ごとの本文（answer_key の units を根拠の本文の JSON から引く）。"""
    ix = PolicyIndex(text_json)
    ak = {r["function"]: r for r in answer_key}
    return {
        c["function"]: [unit_text(ix, u) for u in (ak.get(c["function"]) or {}).get("units", [])]
        for c in gold_cards
    }


def build_map(
    pdf_id: str,
    gold_cards: list[dict],
    gold_text: dict[str, list[str]],
    gen_cards: list[dict],
) -> dict:
    """1 つの PDF の対応付け。根拠の本文は合成カードの evidence_text（pdoc を開かない）。採点結果を見ない。"""
    ptext = {c["function"]: c.get("evidence_text") or "" for c in gen_cards}
    fmap, fdetail = match_functions(gold_cards, gold_text, gen_cards, ptext)
    gby = {c["function"]: c for c in gold_cards}
    pby = {c["function"]: c for c in gen_cards}
    funcs = {}
    for gf, pf in fmap.items():
        amap, fmaps, amb = match_args(gby[gf]["inputs"], pby[pf]["inputs"])
        funcs[gf] = {
            "gen": pf,
            "args": amap,
            "fields": fmaps,
            "ambiguous_args": amb,
            "unmapped_gold_args": [i["name"] for i in gby[gf]["inputs"] if i["name"] not in amap],
            "extra_gen_args": [
                i["name"] for i in pby[pf]["inputs"] if i["name"] not in amap.values()
            ],
        }
    return {
        "pdf_id": pdf_id,
        "functions": funcs,
        "function_scores": fdetail,
        "unmatched_gold": [c["function"] for c in gold_cards if c["function"] not in fmap],
        "extra_gen": [c["function"] for c in gen_cards if c["function"] not in fmap.values()],
        "n_gold": len(gold_cards),
        "n_gen": len(gen_cards),
    }


def is_identity(mp: dict, cards: list[dict]) -> list[str]:
    """恒等の対応になっていない正解の関数（逆対照用。空なら恒等）。"""
    bad = []
    for c in cards:
        m = mp["functions"].get(c["function"])
        names = [i["name"] for i in c["inputs"]]
        if m is None or m["gen"] != c["function"] or m["args"] != {n: n for n in names}:
            bad.append(c["function"])
    return bad


ADAPTER = '''"""採点用アダプタ（評価側が自動生成）。正解の名前で呼ばれたら生成した関数へ引数を写して渡す。"""
import inspect

_SRC = {src!r}
_MAP = {mp!r}
_G = {{"__name__": "_generated"}}
exec(compile(_SRC, "_generated", "exec"), _G)


def _bind(gold_fn, m):
    target = _G[m["gen"]]
    takes_calendar = {cal!r} in inspect.signature(target).parameters

    def call(**kw):
        args = dict(m.get("fill") or {{}})
        for g, p in m["args"].items():
            if g not in kw:
                continue
            v = kw[g]
            fm = m["fields"].get(g)
            if fm is not None and isinstance(v, list):
                v = [{{fm[k]: x for k, x in it.items() if k in fm}} if isinstance(it, dict) else it for it in v]
            args[p] = v
        if takes_calendar and {cal!r} in kw:
            args[{cal!r}] = kw[{cal!r}]
        return target(**args)

    call.__name__ = gold_fn
    return call


for _g, _m in _MAP.items():
    if _m["gen"] in _G:
        globals()[_g] = _bind(_g, _m)
'''


def adapter_source(gen_src: str, mp: dict, *, fill_extra: dict | None = None) -> str:
    """fill_extra（診断用・主指標には使わない）：生成側にだけある引数に入れる値 {関数: {引数: 値}}。"""
    funcs = {
        g: {
            "gen": m["gen"],
            "args": m["args"],
            "fields": m.get("fields", {}),
            "fill": (fill_extra or {}).get(g, {}),
        }
        for g, m in mp["functions"].items()
    }
    return ADAPTER.format(src=gen_src, mp=funcs, cal=CALENDAR_ARG)


def none_fill(mp: dict) -> dict:
    """診断：生成側にだけある引数に None を明示的に渡す（「渡されなかった除外事由は該当しない」が働かない状態）。"""
    return {g: {a: None for a in m["extra_gen_args"]} for g, m in mp["functions"].items()}


def neutral_fill(mp: dict, gen_cards: list[dict]) -> dict:
    """診断：生成側にだけある引数を「該当しない」とみなす値（bool は False・int は 0）。date・list は補わない。"""
    by = {c["function"]: c for c in gen_cards}
    out = {}
    for g, m in mp["functions"].items():
        ins = {i["name"]: i for i in by[m["gen"]]["inputs"]}
        out[g] = {
            a: (False if ins[a]["type"] == "bool" else 0)
            for a in m["extra_gen_args"]
            if ins[a]["type"] in ("bool", "int")
        }
    return out


def load_cards_file(path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

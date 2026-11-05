"""段 K：規定の発見とタスクカードの合成（PDF から読んだ候補だけから作る）。

予測の入力は doc.pdf だけで、実装する関数の宣言（タスクカード）は与えられない。J1 の候補の一覧を LLM に見せ、
計算・判定の規定をすべて数え上げさせ、規定ごとに関数の宣言と根拠の単位を書かせる。値（金額・日数）は書かせない。
解答は決定的に検査し、通ったものだけを合成カードにする。落ちたものは問題として残す（黙って補わない）。
呼び出しの取り決めは文書に依存しないプロジェクトの規約（configs/conventions.yaml）を付ける。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from ..common.paths import CONFIGS, WORK
from . import d_spec, idents, k_lint
from .context import footnote_items
from .j_detect import _is_example_box, candidates, render_candidates
from .llm import Req
from .prompts import fill

if TYPE_CHECKING:
    from .pipeline import DocState
    from .policy_index import PolicyIndex

# v2：判定の条件を 1 つずつ入力に・額の関数も条件の入力。v3：事実そのもの（日付・行ごとの bool・月と端日数）を入力に。
# v4：除外事由の bool に exclusion を付ける（conventions の omitted）
PROMPT_VERSION = "k_cards_p1"  # 既定。実際の版は pipeline.yaml の k.prompt
_CONST = re.compile(r"\{const:[^}]+\}")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,60}$")
TYPES = {"int", "bool", "date", "list"}
FIELD_TYPES = {"int", "bool", "date"}
ORIGINS = {"claim_fact", "assessment", "policy", "computed"}
OUT_BY_KIND = {"calculation": {"int", "date"}, "decision": {"bool"}}
# 自己テストの乱数の値域（文書に依存しない目安。設定に置く値ではなく型の既定）
RANGES = {
    "JPY": (0, 100_000_000),
    "DAY": (0, 3650),
    "MONTH": (0, 240),
    "YEAR": (0, 100),
    "GRADE": (1, 14),
    "COUNT": (0, 100),
    "HOUR": (0, 744),  # 1 か月の時間数
    "MIN": (0, 44_640),  # 1 か月の分数
    "INDEX": (0, 100_000),  # 物価指数などの指数
    None: (0, 1_000_000),
}
DATE_RANGE = ("2024-01-01", "2027-12-31")


def _strings(o) -> list[str]:
    if isinstance(o, str):
        return [o]
    if isinstance(o, dict):
        return [
            s
            for k, v in o.items()
            if k not in ("id", "src", "bbox", "page", "type", "kind", "semantic_type")
            for s in _strings(v)
        ]
    if isinstance(o, list):
        return [s for v in o for s in _strings(v)]
    return []


def unit_text(ix: PolicyIndex, uid: str) -> str:
    n = ix.by_id.get(uid)
    if n is None and "__n" in uid:
        b = ix.by_id.get(uid.split("__n")[0]) or {}
        n = next(({"text": it["raw"]} for it in footnote_items(b) if it["id"] == uid), None)
    if n is None:
        return ""
    # 子の条・段落まで含めると条全体になってしまうので、単位そのものの文字列だけを取る
    own = {
        k: v for k, v in n.items() if k not in ("children", "body", "paragraphs", "items", "blocks")
    }
    return _CONST.sub("", " ".join(ix.expand(s) for s in _strings(own)))


def article_units(ix: PolicyIndex, units: list[str]) -> list[str]:
    """根拠の単位と同じ条・特約（container）に属する、本文を持つ単位の id（文書の順）"""
    conts = {ix.container(u) for u in units} - {None}
    return [
        u for u in ix.order if ix.container(u) in conts and isinstance(ix.by_id[u].get("text"), str)
    ]


def example_texts(ix: PolicyIndex, units: list[str]) -> list[str]:
    """同じ条の設例の囲みの文（{const:…} を残した原文）。点検 example_quantity_unused と K-R の証拠に使う"""
    return [ix.by_id[u]["text"] for u in article_units(ix, units) if _is_example_box(ix, u)]


def article_context(ix: PolicyIndex, units: list[str], max_chars: int = 6000) -> str:
    """K-R に渡す、同じ条の全段落と設例（値は展開する）"""
    lines = []
    for u in article_units(ix, units):
        tag = "設例" if _is_example_box(ix, u) else "本文"
        lines.append(f"- [{u}]（{tag}）{ix.expand(ix.by_id[u]['text'])}")
    t = "\n".join(lines)
    return t if len(t) <= max_chars else t[:max_chars] + "…"


def conventions() -> dict:
    return yaml.safe_load((CONFIGS / "conventions.yaml").read_text(encoding="utf-8"))


# 入力の単位の語彙（正本は configs/conventions.yaml の units。null は単位なし）
UNITS = {*conventions()["units"], None}
if UNITS - set(RANGES):
    raise RuntimeError(
        f"単位の値域が無い: {sorted(map(str, UNITS - set(RANGES)))}（k_cards.RANGES に足す）"
    )


def conventions_text() -> str:
    """プロンプトの <<CONVENTIONS>> に入れる箇条書き。"""
    return "\n".join(
        f"- {k}: {'、'.join(map(str, v))}" if isinstance(v, list) else f"- {v}"
        for k, v in conventions().items()
    )


def load_shots(version: str = "v1") -> list[dict]:
    return json.loads((WORK / "shots" / f"k_cards_{version}.json").read_text(encoding="utf-8"))


def render_shots(shots: list[dict]) -> str:
    out = []
    for i, s in enumerate(shots, 1):
        out.append(
            f"## 例{i}：約款の該当箇所\n{s['context']}\n## 例{i}：関数の宣言\n"
            f"{json.dumps(s['rules'], ensure_ascii=False)}\n"
        )
    return "\n".join(out)


# 被覆の監査（決定的）：強い手掛かりを持つのに、どのカードの根拠にも入らなかった候補を K に 1 回だけ見せ直す
RESCAN_VERSION = "k_rescan_p1"  # 既定。pipeline.yaml の k.rescan_prompt で変える
STRONG_TABLES = {
    "table:grade_schedule",
    "table:rate",
    "table:benefit_schedule",
    "table:coefficient",
    "table:surgery_schedule",
    "table:exclusions",
    "table:conditions",
    "table:plan_matrix",
}
_NEG = re.compile(r"支払いません|支払わない|お支払いしません")
_AMT = re.compile(r"の額は|額とします|を限度と|を乗じ|を差し引|いずれか(低|高|少な|多)い")


def strong(c: dict) -> bool:
    """計算・判定の強い手掛かり：規定の表・判定の図・算式、除外事由の文、定数を伴う額・限度の文。"""
    cs = set(c["cues"])
    if cs & STRONG_TABLES or any(x.startswith("figure:") for x in cs) or "formula" in cs:
        return True
    return c["kind"] in ("paragraph", "item", "footnote") and bool(
        _NEG.search(c["text"]) or ("const" in cs and _AMT.search(c["text"]))
    )


def uncovered(cands: list[dict], cards: list[dict]) -> list[dict]:
    cov = {u for c in cards for u in c.get("evidence_units", [])}
    return [c for c in cands if strong(c) and c["id"] not in cov]


def make_rescan_request(
    doc_id: str,
    ix,
    cands: list[dict],
    cards: list[dict],
    miss: list[dict],
    *,
    model: str,
    max_tokens: int,
    shots_text: str,
    version: str = RESCAN_VERSION,
) -> Req:
    conts = {c["container"] for c in miss}
    show = [
        c for c in cands if c["container"] in conts
    ]  # 見落としの候補と同じ条の候補も文脈として見せる
    existing = [
        {
            "function": c["function"],
            "title": c.get("title"),
            "kind": c["kind"],
            "units": c["evidence_units"],
        }
        for c in cards
    ]
    t = fill(
        version,
        [
            ("CONVENTIONS", conventions_text()),
            ("SHOTS", shots_text),
            ("EXISTING", json.dumps(existing, ensure_ascii=False)),
            ("CANDIDATES", render_candidates(ix, show, max_chars=900)),
        ],
    )
    return Req(
        stage="K",
        doc_id=doc_id,
        unit="rescan",
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=version,
        model=model,
    )


def merge_rescan(
    cards: list[dict],
    units_by: dict[str, list[str]],
    new_cards: list[dict],
    new_units: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    """再走査のカードを足す（その場で cards・units_by を更新）。名前の重複と、根拠がすべて既存のカードに
    含まれるもの（同じ規定の言い換え）は足さない。戻り値：(足した関数, 足さなかった理由)。"""
    cov = {u for c in cards for u in c["evidence_units"]}
    added, dropped = [], []
    for c in new_cards:
        fn = c["function"]
        if fn in units_by:
            dropped.append(f"{fn}: duplicate name")
        elif set(c["evidence_units"]) <= cov:
            dropped.append(f"{fn}: evidence already covered")
        else:
            cards.append(c)
            units_by[fn] = new_units[fn]
            cov |= set(c["evidence_units"])  # 同じ根拠の再走査カードを 2 件足さない
            added.append(fn)
    return added, dropped


def split_by_container(cands: list[dict]) -> list[list[dict]]:
    """候補を条（container）のまとまりを崩さずに、件数がほぼ半分になる 2 つに分ける。"""
    groups: dict[str, list[dict]] = {}
    for c in cands:
        groups.setdefault(c["container"], []).append(c)
    half, first, second = len(cands) / 2, [], []
    for g in groups.values():
        (
            first
            if len(first) < half and (not first or len(first) + len(g) <= half or not second)
            else second
        ).extend(g)
    return [x for x in (first, second) if x]


def merge_parts(parts: list[tuple[list[dict], dict[str, list[str]], list[str]]]):
    """分けて呼んだ K の解答を合わせる。同じ関数名は先の方を残す。"""
    cards, units_by, probs = [], {}, []
    for cs, ub, pr in parts:
        probs += pr
        for c in cs:
            if c["function"] in units_by:
                probs.append(f"{c['function']}: duplicate across parts (dropped)")
                continue
            cards.append(c)
            units_by[c["function"]] = ub[c["function"]]
    return cards, units_by, probs


def make_request(
    doc_id: str,
    ix,
    cands: list[dict],
    *,
    model: str,
    max_tokens: int,
    shots_text: str,
    version: str = PROMPT_VERSION,
    unit: str = "cards",
) -> Req:
    t = fill(
        version,
        [
            ("CONVENTIONS", conventions_text()),
            ("SHOTS", shots_text),
            ("CANDIDATES", render_candidates(ix, cands, max_chars=900)),
        ],
    )
    return Req(
        stage="K",
        doc_id=doc_id,
        unit=unit,
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=version,
        model=model,
    )


def _check_input(fn: str, i, seen: set[str]) -> tuple[dict | None, list[str]]:
    probs: list[str] = []
    if not isinstance(i, dict):
        return None, [f"{fn}: input is not an object"]
    name, typ, unit = i.get("name"), i.get("type"), i.get("unit")
    # カードの名前の規則（英小文字で始まる 2 文字以上）に、生成コードの識別子の規則（予約語・補助の名前）を重ねる
    if not isinstance(name, str) or not NAME.match(name) or idents.name_problem(name, role="input"):
        probs.append(f"{fn}: bad input name {name!r}")
    elif name in seen:
        probs.append(f"{fn}: duplicate input {name}")
    if typ not in TYPES:
        probs.append(f"{fn}.{name}: bad type {typ!r}")
    if unit not in UNITS:
        probs.append(f"{fn}.{name}: bad unit {unit!r}")
    if typ in ("bool", "date") and unit is not None:
        probs.append(f"{fn}.{name}: {typ} must have unit null")
    if probs:
        return None, probs
    out = {
        "name": name,
        "type": typ,
        "unit": unit,
        "desc": str(i.get("desc") or ""),
        "origin": i.get("origin") if i.get("origin") in ORIGINS else "claim_fact",
        "nullable": True,
    }
    if (
        i.get("exclusion") is True
    ):  # 除外事由の印は bool の入力だけに付ける。それ以外は印を外して問題に残す
        if typ == "bool":
            out["exclusion"] = True
        else:
            probs.append(f"{fn}.{name}: exclusion on non-bool input (ignored)")
    if typ == "int":
        out["min"], out["max"] = RANGES[unit]
    elif typ == "date":
        out["min"], out["max"] = DATE_RANGE
    elif typ == "list":
        fields, fseen = [], set()
        for f in i.get("fields") or []:
            if (
                not isinstance(f, dict)
                or not NAME.match(str(f.get("name")))
                or f.get("type") not in FIELD_TYPES
                or f.get("unit") not in UNITS
                or f["name"] in fseen
            ):
                probs.append(f"{fn}.{name}: bad field {f!r}")
                continue
            fseen.add(f["name"])
            ff = {
                "name": f["name"],
                "type": f["type"],
                "unit": f.get("unit"),
                "desc": str(f.get("desc") or ""),
            }
            if f["type"] == "int":
                ff["min"], ff["max"] = RANGES[f.get("unit")]
            fields.append(ff)
        if not fields:
            probs.append(f"{fn}.{name}: list without valid fields")
            return None, probs
        out["fields"], out["max_items"] = fields, 5
    return out, probs


def interpret(
    doc_id: str, parsed, cands: list[dict]
) -> tuple[list[dict], dict[str, list[str]], list[str]]:
    """LLM の解答 → (合成カード, 関数ごとの根拠単位, 問題)。検査に落ちた規定はカードにしない。"""
    valid = {c["id"] for c in cands}
    by_cont: dict[str, list[str]] = {}
    for c in cands:
        by_cont.setdefault(c["container"], []).append(c["id"])
    conv = conventions()
    cards: list[dict] = []
    units_by: dict[str, list[str]] = {}
    probs: list[str] = []
    rules = (parsed or {}).get("rules") if isinstance(parsed, dict) else None
    if not isinstance(rules, list):
        return [], {}, ["K: no rules array"]
    for r in rules:
        if not isinstance(r, dict):
            probs.append("K: rule is not an object")
            continue
        fn, kind = r.get("function"), r.get("kind")
        out_t = (
            (r.get("output") or {}).get("type")
            if isinstance(r.get("output"), dict)
            else r.get("output")
        )
        bad = []
        if (
            not isinstance(fn, str)
            or not NAME.match(fn)
            or idents.name_problem(fn, role="function")
        ):
            bad.append(f"bad function name {fn!r}")
        elif fn in units_by:
            bad.append(f"duplicate function {fn}")
        if kind not in OUT_BY_KIND:
            bad.append(f"bad kind {kind!r}")
        elif out_t not in OUT_BY_KIND[kind]:
            bad.append(f"output {out_t!r} does not fit kind {kind}")
        inputs, seen = [], set()
        for i in r.get("inputs") or []:
            ci, p = _check_input(str(fn), i, seen)
            probs += p
            if ci:
                seen.add(ci["name"])
                inputs.append(ci)
        if not inputs:
            bad.append("no valid inputs")
        units = []
        for u in r.get("units") or []:
            if not isinstance(u, str):
                continue
            if u not in valid and "/" in u and u.rsplit("/", 1)[1] in valid:
                u = u.rsplit("/", 1)[1]
            if u in valid:
                units.append(u)
            elif u in by_cont:
                units += by_cont[u]
            else:
                probs.append(f"{fn}: unknown unit {u}")
        units = list(dict.fromkeys(units))
        if not units:
            bad.append("no valid evidence units")
        if bad:
            probs.append(f"{fn}: rejected: {'; '.join(bad)}")
            continue
        units_by[fn] = units
        cards.append(
            {
                "task_id": f"{doc_id}:{fn}",
                "content_id": doc_id,
                "function": fn,
                "title": str(r.get("title") or ""),
                "kind": kind,
                "hint": "auto",
                "inputs": inputs,
                # K のプロンプトは整数の出力を「支払う額」と定める（k_cards_p1 の規定の種類と output の形）。
                # 両コーパスの正解でも整数の出力はすべて円なので、整数なら JPY とする
                "output": {
                    "type": out_t,
                    "unit": "JPY" if out_t == "int" else None,
                    "nullable": True,
                },
                "conventions": conv,
                "evidence_units": units,
            }
        )
    return cards, units_by, probs


def rescan_verdicts(parsed, miss_ids: list[str]) -> dict:
    """再走査の候補ごとの裁定を数える。答えの無い候補は unanswered に残す。"""
    vs = (
        [v for v in ((parsed or {}).get("verdicts") or []) if isinstance(v, dict)]
        if isinstance(parsed, dict)
        else []
    )
    by = {str(v.get("id")): str(v.get("decision")) for v in vs}
    cnt: dict[str, int] = {}
    for d in by.values():
        d = d if d in ("added", "existing", "skip") else "invalid"
        cnt[d] = cnt.get(d, 0) + 1
    return {"counts": cnt, "unanswered": [i for i in miss_ids if i not in by]}


@dataclass
class KWork:
    """K の途中の状態（PDF ごと）。再走査・改修がカードと根拠を書き換え、最後に DocState へ移す。"""

    cands: list[dict]
    cards: list[dict]
    units_by: dict[str, list[str]]


def _rescan(
    llm,
    docs: list[tuple[DocState, KWork]],
    *,
    model: str,
    max_tokens: int,
    shots_text: str,
    version: str = RESCAN_VERSION,
) -> None:
    """被覆の監査と再走査。見落としの候補がある PDF だけ、1 回だけ K を呼び直してカードを足す。"""
    reqs, live = [], []
    for s, w in docs:
        cands, cards = w.cands, w.cards
        miss = uncovered(cands, cards)
        s.j["rescan"] = {"n_uncovered": len(miss), "uncovered": [c["id"] for c in miss]}
        if miss:
            reqs.append(
                make_rescan_request(
                    s.doc_id,
                    s.ix,
                    cands,
                    cards,
                    miss,
                    model=model,
                    max_tokens=max_tokens,
                    shots_text=shots_text,
                    version=version,
                )
            )
            live.append((s, w))
    for (s, w), resp in zip(live, llm.complete(reqs) if reqs else []):
        cands, cards, units_by = w.cands, w.cards, w.units_by
        if not resp.ok:  # 再走査の失敗は 1 回目のカードを残して続ける（問題として記録する）
            s.j["rescan"]["error"] = str(resp.err)
            continue
        new_cards, new_units, probs = interpret(s.doc_id, resp.parsed, cands)
        added, dropped = merge_rescan(cards, units_by, new_cards, new_units)
        s.j["rescan"].update(
            {
                "added": added,
                "dropped": dropped,
                "probs": probs,
                "verdicts": rescan_verdicts(resp.parsed, s.j["rescan"]["uncovered"]),
            }
        )


# 呼び出し口の改修 K-R：点検（k_lint）で旗の立ったカードだけを 1 回直す。入力はカード・根拠・旗だけ
REPAIR_VERSION = "k_repair_p1"  # 旗ごとの直し方・同じ条の全段落と設例を証拠に渡す
# condition_in_amount は K の規則（額の関数も支払の条件を受け取る）と食い違うので、改修には使わない（記録だけ）
REPAIR_FLAGS = {
    "base_quantity_missing": "額の関数なのに、金額の入力が既払額・限度額などだけで、支払の基礎となる量（支出した費用・損害の額・日数など）を受け取っていない",
    "affirmative_condition_missing": "判定の関数の入力が除外事由だけで、支払う側の要件（請求・指示・届出など、満たせば支払う条件）を受け取っていない",
    "bundled_input": "複数の事由（「次のいずれか」の列挙・表の行）を 1 つの真偽の入力にまとめている",
    "policy_period_input": "保険期間の始期・終期を入力にしている（規定の条が自分で定めていなければ、すべての規定に共通の前提なので入力にしない）",
    "defined_quantity_as_date": "根拠が名前を付けて定義する量（経過月数・端日数など）で計算するのに、日付を受け取っている",
    "defined_quantity_missing": "根拠が名前を付けて使う量（経過月数・端日数など）を、どの入力も表していない",
    "negated_requirement": "真偽の入力が、支払の手続・医療の行為が無いこと（「〜を伴わない」「〜が行われなかった」）を述べている。"
    "その入力を、行為が行われたかを問う肯定形の要件（exclusion なし）に書き換える。新しい入力は作らない",
    "example_quantity_unused": "同じ条の設例が使う量を、どの入力も表していない。設例と本文に現れるその量を入力に足す",
}


def repair_targets(cards: list[dict], ix) -> list[tuple[dict, list[dict]]]:
    """(カード, 改修に使う旗) の組。根拠の本文を一時的に付けて点検する（カードは変えない）。"""
    out = []
    for c in cards:
        tmp = dict(
            c,
            evidence_text=" ".join(unit_text(ix, u) for u in c["evidence_units"]),
            example_text=example_texts(ix, c["evidence_units"]),
        )
        fl = [f for f in k_lint.lint_card(tmp) if f["flag"] in REPAIR_FLAGS]
        if fl:
            out.append((c, fl))
    return out


def make_repair_request(
    doc_id: str,
    ix,
    cands: list[dict],
    card: dict,
    flags: list[dict],
    *,
    model: str,
    max_tokens: int,
    version: str = REPAIR_VERSION,
) -> Req:
    """旗の立ったカード 1 枚を直させる依頼。version は pipeline.yaml の k.repair_prompt（環境変数で上書きできる）。"""
    conts = {c["container"] for c in cands if c["id"] in set(card["evidence_units"])}
    show = [c for c in cands if c["container"] in conts or c["id"] in set(card["evidence_units"])]
    cur = {k: card[k] for k in ("function", "title", "kind", "inputs", "output")}
    cur["units"] = card["evidence_units"]
    lines = []
    for f in flags:
        lines.append(
            f"- {f['flag']}：{REPAIR_FLAGS[f['flag']]}"
            + (f"（入力 {f['input']}）" if f.get("input") else "")
            + (f"（設例の量「{f['note']}」）" if f["flag"] == "example_quantity_unused" else "")
        )
    t = fill(
        version,
        [
            ("CONVENTIONS", conventions_text()),
            ("CARD", json.dumps(cur, ensure_ascii=False)),
            ("FLAGS", "\n".join(lines)),
            ("CANDIDATES", render_candidates(ix, show, max_chars=1500)),
            ("ARTICLE", article_context(ix, card["evidence_units"])),
        ],
    )  # ARTICLE は v4 から（v3 以前は置き場所が無い）
    return Req(
        stage="K",
        doc_id=doc_id,
        unit=f"repair:{card['function']}",
        prompt=t,
        max_tokens=max_tokens,
        prompt_version=version,
        model=model,
    )


def _input_sig(card: dict) -> list[tuple]:
    """入力の形（名前・型・単位・除外か）。改修で変わったかの判定に使う。"""
    return [(i["name"], i["type"], i.get("unit"), i.get("exclusion")) for i in card["inputs"]]


def apply_repair(
    doc_id: str, card: dict, parsed, cands: list[dict]
) -> tuple[dict | None, list[str], str]:
    """改修の解答を検査して、置き換えるカードを返す。(新しいカード or None, 根拠, 理由)。
    名前・種別が変わった・検査に落ちた・変更なしのときは None（元のカードを残す）。"""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rule"), dict):
        return None, [], "no rule"
    r = parsed["rule"]
    if r.get("function") != card["function"] or r.get("kind") != card["kind"]:
        return None, [], "function or kind changed"
    if parsed.get("changed") is False:
        return None, [], "unchanged"
    new, units, probs = interpret(doc_id, {"rules": [r]}, cands)
    if not new:
        return None, [], "rejected: " + "; ".join(probs)
    if _input_sig(new[0]) == _input_sig(card) and units[card["function"]] == card["evidence_units"]:
        return None, [], "unchanged"
    return new[0], units[card["function"]], "replaced"


def _repair(
    llm,
    docs: list[tuple[DocState, KWork]],
    *,
    model: str,
    max_tokens: int,
    version: str = REPAIR_VERSION,
) -> None:
    """点検の旗が立ったカードを 1 回だけ直させる（K-R）。置き換えたカードは KWork を書き換える。"""
    reqs, live = [], []
    for s, w in docs:
        tg = repair_targets(w.cards, s.ix)
        s.j["k_repair"] = {"n_targets": len(tg), "results": {}}
        for c, fl in tg:
            reqs.append(
                make_repair_request(
                    s.doc_id,
                    s.ix,
                    w.cands,
                    c,
                    fl,
                    model=model,
                    max_tokens=max_tokens,
                    version=version,
                )
            )
            live.append((s, w, c, fl))
    for (s, w, c, fl), resp in zip(live, llm.complete(reqs) if reqs else []):
        cands, cards, units_by = w.cands, w.cards, w.units_by
        rec = {"flags": [f["flag"] for f in fl]}
        if not resp.ok:
            rec["result"] = f"error: {resp.err}"
        else:
            new, units, why = apply_repair(s.doc_id, c, resp.parsed, cands)
            rec["result"] = why
            rec["flag_answers"] = (
                (resp.parsed or {}).get("flag_answers") if isinstance(resp.parsed, dict) else None
            )
            if new:
                k = next(i for i, x in enumerate(cards) if x["function"] == c["function"])
                cards[k] = new
                units_by[c["function"]] = units
                rec["inputs_before"] = [i["name"] for i in c["inputs"]]
                rec["inputs_after"] = [i["name"] for i in new["inputs"]]
        s.j["k_repair"]["results"][c["function"]] = rec


def run(
    llm,
    docs,
    *,
    model: str,
    max_tokens: int,
    rescan: bool = True,
    version: str = PROMPT_VERSION,
    rescan_version: str = RESCAN_VERSION,
    repair: bool = False,
    repair_version: str = REPAIR_VERSION,
    shots_text: str | None = None,
) -> None:
    """各 DocState に合成カード（s.cards）と文脈（s.ctx）を入れる。shots_text は手本（None なら work/shots から読む）。"""
    if shots_text is None:
        shots_text = render_shots(load_shots())
    # id(DocState) → K の途中の状態（K が読めた PDF だけ）。DocState は live が持ち続けるので、id は run の中でだけ有効
    work: dict[int, KWork] = {}
    reqs, live = [], []
    for s in docs:
        cands = candidates(s.ix)
        s.j = {"n_candidates": len(cands), "candidates": [c["id"] for c in cands]}
        reqs.append(
            make_request(
                s.doc_id,
                s.ix,
                cands,
                model=model,
                max_tokens=max_tokens,
                shots_text=shots_text,
                version=version,
            )
        )
        live.append((s, cands))
    failed = []
    for (s, cands), resp in zip(live, llm.complete(reqs)):
        s.j["attempts"] = (
            resp.attempts
        )  # この run での呼び出し回数（0＝前の run のキャッシュ、2 以上＝失敗の呼び直し）
        if not resp.ok:
            failed.append((s, cands, resp.err))
            continue
        cards, units_by, probs = interpret(s.doc_id, resp.parsed, cands)
        skipped = [x for x in (resp.parsed or {}).get("skipped", []) if isinstance(x, dict)]
        s.j.update(
            {
                "by_function": units_by,
                "unmatched": skipped,
                "probs": probs,
                "n_cards_first": len(cards),
            }
        )
        work[id(s)] = KWork(cands, cards, units_by)
    if failed:  # 出力の途中切断・解析失敗：その PDF だけ、候補を 2 つに分けて呼び直す
        preqs, plive = [], []
        for s, cands, err in failed:
            parts = split_by_container(cands)
            s.j["split"] = {
                "first_error": str(err),
                "n_parts": len(parts),
                "sizes": [len(x) for x in parts],
            }
            for k, part in enumerate(parts, 1):
                preqs.append(
                    make_request(
                        s.doc_id,
                        s.ix,
                        part,
                        model=model,
                        max_tokens=max_tokens,
                        shots_text=shots_text,
                        version=version,
                        unit=f"cards_part{k}",
                    )
                )
            plive.append((s, cands, len(parts)))
        resps = iter(llm.complete(preqs))
        for s, cands, n in plive:
            got = [next(resps) for _ in range(n)]
            bad = [r.err for r in got if not r.ok]
            if bad:
                s.j["split"]["errors"] = [str(b) for b in bad]
            good = [r for r in got if r.ok]
            if not good:  # どの部分も読めなければ、その PDF は K の失敗
                s.error = f"K llm (split): {bad[0]}"
                continue
            # 一部の部分だけ読めたときは、読めた部分のカードで続ける（PDF 全体を落とさない。失敗した部分は記録に残す）
            cards, units_by, probs = merge_parts(
                [interpret(s.doc_id, r.parsed, cands) for r in good]
            )
            if bad:
                probs.append(f"K split: {len(bad)}/{n} parts failed ({bad[0]})")
            skipped = [
                x for r in good for x in (r.parsed or {}).get("skipped", []) if isinstance(x, dict)
            ]
            s.j.update(
                {
                    "by_function": units_by,
                    "unmatched": skipped,
                    "probs": probs,
                    "n_cards_first": len(cards),
                }
            )
            work[id(s)] = KWork(cands, cards, units_by)
    done = [
        (s, work[id(s)]) for s, _ in live if id(s) in work
    ]  # live の順（LLM への依頼の順を変えない）
    if rescan:
        try:
            _rescan(
                llm,
                done,
                model=model,
                max_tokens=max_tokens,
                shots_text=shots_text,
                version=rescan_version,
            )
        except Exception as e:  # noqa: BLE001  再走査の失敗は 1 回目のカードで続ける（記録だけ）
            for s, _ in done:
                s.j.setdefault("rescan", {})["error"] = f"rescan: {e}"
    if repair:
        try:
            _repair(llm, done, model=model, max_tokens=max_tokens, version=repair_version)
        except Exception as e:  # noqa: BLE001  改修の失敗は改修前のカードで続ける（記録だけ）
            for s, _ in done:
                s.j.setdefault("k_repair", {})["error"] = f"k_repair: {e}"
    for s, w in done:
        cards, units_by = w.cards, w.units_by
        units = list(dict.fromkeys(u for c in cards for u in units_by[c["function"]]))
        s.j.update({"by_function": units_by, "units": units, "n_cards": len(cards)})
        for c in cards:  # 根拠の本文（採点側の対応付け M が pdoc を開かずに済むように残す）
            c["evidence_text"] = " ".join(unit_text(s.ix, u) for u in c["evidence_units"])
            c["example_text"] = example_texts(
                s.ix, c["evidence_units"]
            )  # 点検の旗 example_quantity_unused
        s.cards = cards
        if not cards:
            s.error = "K: no valid rule found"
            continue
        s.ctx = d_spec.doc_context(s.ix, units)
        s.units_source = "K"

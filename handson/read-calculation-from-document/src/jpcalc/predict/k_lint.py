"""合成カードの呼び出し口の決定的な点検（AI を使わない）。

合成カードと、カードに残した根拠の本文（evidence_text）だけを読む。旗を立てるだけで、カードは変えない。
旗はいずれも約款の読み方の一般原則から決めた（正解の呼び出し口は見ない）：
- base_quantity_missing：額の関数なのに、金額の入力が既払額・限度額・保険金額だけで、支払の基礎となる量
  （損害・費用の額、日数・回数・等級）を受け取らない。
- affirmative_condition_missing：判定の入力が除外事由だけで、支払う側の要件（原則）を 1 つも受け取らない。
- bundled_input：「次のいずれか」「いずれかに該当」のように、複数の事由を 1 つの真偽にまとめた入力。
- condition_in_amount：額の関数が、除外の印の無い条件の真偽を受け取る（支払の可否は判定の関数の仕事）。
- policy_period_input：保険期間の始期・終期を受け取る（保険期間内かどうかは全規定に共通の前提）。
- defined_quantity_as_date：根拠が経過月数・経過日数などの量を定義しているのに、日付を受け取る。
- defined_quantity_missing：根拠が名前を付けて使う量（経過月数・端日数など）を、どの入力も表していない（日付も受け取らない）。
- negated_requirement：真偽の入力が、支払の手続・医療の行為が無いこと（「医師の治療を伴わない」など）を述べる。
  要件の欠如は、その行為が行われたかを問う肯定形の要件にする。事故の態様（運転資格を有しない など）は対象外。
- example_quantity_unused：同じ条の設例（example_text）が使う量（「〜の額が{値}」）を、どの入力も表していない。
語の一覧は configs/k_lint_terms.yaml。
"""

from __future__ import annotations

import re
from functools import lru_cache

import yaml

from ..common.paths import CONFIGS

PRIOR_OR_CAP = re.compile(
    r"既に|既払|支払った|限度|上限|保険金額|協定保険価額|基準給付額|日額|支払割合"
)
BASIS_AMOUNT = re.compile(r"損害|費用|実費|支出|要した|代金|価額|額")
BUNDLED = re.compile(r"いずれか|次の(各号|事由|いずれか)?に?該当|次に掲げる|^次の")
POLICY_PERIOD = re.compile(r"保険期間の(開始|終了|始期|終期)|保険期間が(始|終)|責任期間")
DEFINED_QTY = re.compile(r"経過(月|日|年)数|経過した(月|日|年)数|端日数")
QTY_KEY = {
    "経過月数": "月",
    "経過日数": "日",
    "経過年数": "年",
    "経過した月数": "月",
    "経過した日数": "日",
    "経過した年数": "年",
    "端日数": "端",
}

FLAGS = (
    "base_quantity_missing",
    "affirmative_condition_missing",
    "bundled_input",
    "condition_in_amount",
    "policy_period_input",
    "defined_quantity_as_date",
    "defined_quantity_missing",
    "negated_requirement",
    "example_quantity_unused",
)


@lru_cache(maxsize=1)
def _terms() -> dict:
    t = yaml.safe_load((CONFIGS / "k_lint_terms.yaml").read_text(encoding="utf-8"))
    acts = "|".join(map(re.escape, t["requirement_acts"]))
    negs = "|".join(map(re.escape, t["negations"]))
    kinds = "|".join(map(re.escape, t["example_quantity_kinds"]))
    return {
        "neg_req": re.compile(rf"({acts})[^、。]{{0,{int(t['max_gap'])}}}?({negs})"),
        "qty": re.compile(
            rf"(?:^|[、。]|が|は)([^、。]{{2,30}}?)の(?:{kinds})が\{{const:[^}}]+\}}"
        ),
        "stop": set(t["stop_chars"]),
        "min_overlap": float(t["min_overlap"]),
    }


def _bigrams(s: str, stop: set) -> set[str]:
    s = re.sub(r"\{const:[^}]+\}|\s", "", s)
    return {s[i : i + 2] for i in range(len(s) - 1) if not (set(s[i : i + 2]) & stop)}


def unused_example_quantities(card: dict) -> list[str]:
    """設例の量のうち、同じ文のほかの量と区別できる語が、どの入力の説明にも写らないもの。"""
    tm = _terms()
    stop, lo = tm["stop"], tm["min_overlap"]
    descs = [
        _bigrams(i.get("desc", "") + " " + i.get("name", ""), stop)
        for i in card.get("inputs") or []
    ]
    for f in (i.get("fields") or [] for i in card.get("inputs") or []):
        descs += [_bigrams(x.get("desc", ""), stop) for x in f]
    miss = []
    for t in card.get("example_text") or []:
        qs = [m.group(1) for m in tm["qty"].finditer(t) if "{const" not in m.group(1)]
        for q in qs:
            others = (
                set().union(*[_bigrams(o, stop) for o in qs if o != q]) if len(qs) > 1 else set()
            )
            disc = (_bigrams(q, stop) - others) or _bigrams(q, stop)
            if (
                disc
                and max([len(disc & d) / len(disc) for d in descs] + [0.0]) < lo
                and q not in miss
            ):
                miss.append(q)
    return miss


def _is_money(i: dict) -> bool:
    return i.get("type") == "int" and i.get("unit") == "JPY"


def lint_card(card: dict) -> list[dict]:
    """1 枚のカードの旗。[{flag, input?, note}]"""
    out: list[dict] = []
    ins = card.get("inputs") or []
    ev = card.get("evidence_text") or ""
    kind = card.get("kind")
    out_money = (card.get("output") or {}).get("unit") == "JPY"
    if kind == "calculation" and out_money:
        basis = [
            i
            for i in ins
            if (_is_money(i) and not PRIOR_OR_CAP.search(i.get("desc", "")))
            or (i.get("type") in ("int", "list") and i.get("unit") != "JPY")
        ]
        if not basis:
            out.append({"flag": "base_quantity_missing", "note": "金額の入力が既払額・限度だけ"})
        for i in ins:
            if i.get("type") == "bool" and i.get("exclusion") is not True:
                out.append({"flag": "condition_in_amount", "input": i["name"]})
    if (
        kind == "decision"
        and ins
        and all(i.get("exclusion") is True for i in ins if i.get("type") == "bool")
        and all(i.get("type") == "bool" for i in ins)
    ):
        out.append({"flag": "affirmative_condition_missing", "note": "入力が除外事由だけ"})
    for i in ins:
        d = i.get("desc", "")
        if i.get("type") == "bool" and BUNDLED.search(d):
            out.append({"flag": "bundled_input", "input": i["name"]})
        if i.get("type") == "date" and POLICY_PERIOD.search(d):
            out.append({"flag": "policy_period_input", "input": i["name"]})
    if (
        DEFINED_QTY.search(ev)
        and any(i.get("type") == "date" for i in ins)
        and not any(DEFINED_QTY.search(i.get("desc", "")) for i in ins)
    ):
        out.append({"flag": "defined_quantity_as_date", "note": DEFINED_QTY.search(ev).group(0)})
    for i in ins:
        if i.get("type") == "bool" and _terms()["neg_req"].search(i.get("desc", "")):
            out.append({"flag": "negated_requirement", "input": i["name"]})
    if kind == "calculation":
        for q in unused_example_quantities(card):
            out.append({"flag": "example_quantity_unused", "note": q})
    if not any(i.get("type") == "date" for i in ins):
        descs = "".join(i.get("desc", "") for i in ins)
        for q in dict.fromkeys(m.group(0) for m in DEFINED_QTY.finditer(ev)):
            if q not in descs and not (QTY_KEY[q] == "端" and "端" in descs):
                out.append({"flag": "defined_quantity_missing", "note": q})
    return out


def lint_cards(cards: list[dict]) -> dict:
    """PDF 1 つ分。{function: [旗]}（旗の無いカードは含めない）と件数。"""
    per = {c["function"]: f for c in cards if (f := lint_card(c))}
    counts: dict[str, int] = {}
    for fl in per.values():
        for x in {y["flag"] for y in fl}:
            counts[x] = counts.get(x, 0) + 1
    return {"n_cards": len(cards), "n_flagged": len(per), "counts": counts, "flags": per}

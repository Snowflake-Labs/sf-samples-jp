"""仕様とカードから自己テストの入力を作る（自己テストの層 3：境界・不明値・ランダム）。

境界：仕様の中で入力と比べられ・限度として使われる定数（param・lit・表のキー）の前後
不明：各入力を 1 つずつ None にしたもの
ランダム：タスクカードの値域（min / max）の中
期待値は呼び出し側が参照インタプリタで求める（ここでは入力だけを作る）。
"""

from __future__ import annotations

import datetime as dt
import random

BASE_DATE = dt.date(2024, 4, 1)
MAX_DAY_OFFSET = 3650  # 日付の境界に使う定数の上限（日数として 10 年）


def _consts(spec: dict, rule: dict) -> list[int]:
    out: set[int] = set()
    tables = spec["tables"]

    def walk(e):
        if isinstance(e, dict):
            if "param" in e and "op" not in e:
                out.add(int(spec["params"][e["param"]]["value"]))
            if "lit" in e and "op" not in e:
                out.add(int(e["lit"]))
            if e.get("op") == "lookup":
                out.update(int(r[0]) for r in tables[e["table"]]["rows"])
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)

    walk([s["expr"] for s in rule["steps"]])
    return sorted(out)


def _card_inputs(card: dict) -> dict:
    return {i["name"]: i for i in card["inputs"]}


def _rand_val(i: dict, rng: random.Random, consts: list[int]):
    t = i["type"]
    if t == "bool":
        return rng.choice([True, False])
    if t == "date":
        return BASE_DATE + dt.timedelta(days=rng.randint(-400, 400))
    if t == "list":
        n = rng.randint(0, int(i.get("max_items") or 4))
        return [
            {f["name"]: _rand_val(f, rng, consts) for f in i.get("fields", [])} for _ in range(n)
        ]
    lo, hi = i.get("min"), i.get("max")
    lo = 0 if lo is None else int(lo)
    hi = max(lo + 10, (max(consts) * 3 if consts else 100000)) if hi is None else int(hi)
    r = rng.random()
    if r < 0.35 and consts:
        c = rng.choice(consts)
        return min(hi, max(lo, c + rng.choice([-1, 0, 1])))
    return rng.randint(lo, hi)


def generate(
    spec: dict, rule: dict, card: dict, *, n_random: int = 200, seed: int = 0, deltas=(-1, 0, 1)
) -> list[dict]:
    rng = random.Random(f"{seed}:{rule['function']}")
    ins = _card_inputs(card)
    consts = _consts(spec, rule)
    cases: list[dict] = []

    def base():
        return {k: _rand_val(i, rng, consts) for k, i in ins.items()}

    # 境界：int 入力ごとに定数の前後
    for k, i in ins.items():
        if i["type"] != "int":
            continue
        lo = 0 if i.get("min") is None else int(i["min"])
        hi = None if i.get("max") is None else int(i["max"])
        for c in consts:
            for d in deltas:
                v = c + d
                if v < lo or (hi is not None and v > hi):
                    continue
                x = base()
                x[k] = v
                cases.append({"kind": "boundary", "inputs": x})
    # 日付：起算の境目（日数として意味のある定数だけ。金額などを日数として足すと date の範囲を超える）
    day_consts = [c for c in consts if 0 <= c <= MAX_DAY_OFFSET]
    for k, i in ins.items():
        if i["type"] == "date":
            for c in day_consts:
                for d in deltas:
                    x = base()
                    x[k] = BASE_DATE + dt.timedelta(days=c + d)
                    cases.append({"kind": "boundary", "inputs": x})
    # bool：全組合せ（8 個まで）
    bools = [k for k, i in ins.items() if i["type"] == "bool"]
    if bools and len(bools) <= 3:
        import itertools

        for combo in itertools.product([True, False], repeat=len(bools)):
            x = base()
            x.update(dict(zip(bools, combo)))
            cases.append({"kind": "boundary", "inputs": x})
    # 不明
    for k in ins:
        for _ in range(2):
            x = base()
            x[k] = None
            cases.append({"kind": "unknown", "inputs": x})
    for _ in range(n_random):
        cases.append({"kind": "random", "inputs": base()})
    return cases


def _to_json(v):
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, list):
        return [_to_json(x) for x in v]
    if isinstance(v, dict):
        return {k: _to_json(x) for k, x in v.items()}
    return v


def to_json_inputs(x: dict) -> dict:
    """日付を ISO 文字列に（明細 list の中の日付フィールドも。合成カードで日付のフィールドが出る）。"""
    return {k: _to_json(v) for k, v in x.items()}


def from_json_inputs(x: dict, card: dict) -> dict:
    dates = {i["name"] for i in card["inputs"] if i["type"] == "date"}
    fdates = {
        i["name"]: {f["name"] for f in i.get("fields") or [] if f["type"] == "date"}
        for i in card["inputs"]
        if i["type"] == "list"
    }
    out = {}
    for k, v in x.items():
        if k in dates and v is not None:
            v = dt.date.fromisoformat(v)
        elif fdates.get(k) and isinstance(v, list):
            v = [
                {
                    f: (dt.date.fromisoformat(y) if f in fdates[k] and isinstance(y, str) else y)
                    for f, y in it.items()
                }
                if isinstance(it, dict)
                else it
                for it in v
            ]
        out[k] = v
    return out

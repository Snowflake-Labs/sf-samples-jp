"""T 段：文書だけから作る自己テスト。正解ケースは使わない。

層 1 静的検査：構文・関数名と引数名がタスクカードどおり・許可した import だけ
層 2 設例テスト：設例の (入力, 期待値) で実行。入力の一部が不明で結果が不明になる設例は「判定不能」として数える
層 3 仕様から作るテスト：境界・不明・ランダムの入力を作り、参照インタプリタと生成コードの一致を見る（I の誤り）。
     性質：金額の出力が負でないこと
結果は失敗ごとに「層・関数・入力・期待・実際」を残す。
"""

from __future__ import annotations

import ast
import datetime as dt

from . import casegen, runner

# 許可する import・属性・構文の正本は codegen_check（実行の直前の検査と同じ規則をそのまま使う）
from .codegen_check import check_module
from .interp import Interp


def static_check(src: str, cards: list[dict]) -> list[dict]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError) as e:
        return [{"layer": "static", "function": None, "msg": f"syntax: {e}"}]
    fails = [{"layer": "static", "function": None, "msg": m} for m in check_module(src)]
    defs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for c in cards:
        f = defs.get(c["function"])
        if f is None:
            fails.append({"layer": "static", "function": c["function"], "msg": "missing function"})
            continue
        got = sorted(a.arg for a in f.args.kwonlyargs)
        want = sorted(i["name"] for i in c["inputs"])
        if got != want or f.args.args:
            fails.append(
                {"layer": "static", "function": c["function"], "msg": f"signature {got} != {want}"}
            )
    return fails


def _date_args(card):
    return [i["name"] for i in card["inputs"] if i["type"] == "date"]


def _date_fields(card):
    return {
        i["name"]: [f["name"] for f in i.get("fields") or [] if f["type"] == "date"]
        for i in card["inputs"]
        if i["type"] == "list" and any(f["type"] == "date" for f in i.get("fields") or [])
    }


def _norm_expected(v, card):
    """日付の期待値を date に。時刻付き（'2024-04-04T06:00'）は日付の部分だけを使う。
    解釈できない値は _BAD を返し、その設例は自己テストから外す（1 件でラン全体を落とさない）。"""
    if card["output"]["type"] == "date" and isinstance(v, str):
        try:
            return dt.date.fromisoformat(v[:10])
        except ValueError:
            return _BAD
    return v


_BAD = object()


def run(
    spec: dict,
    src: str,
    cards: list[dict],
    examples: list[dict],
    *,
    n_random: int = 200,
    deltas=(-1, 0, 1),
    timeout: float = 120,
    per_call_timeout: float = 5,
) -> dict:
    cmap = {c["function"]: c for c in cards}
    fails = static_check(src, cards)
    stats = {
        "static_fail": len(fails),
        "example_total": 0,
        "example_pass": 0,
        "example_inconclusive": 0,
        "spec_cases": 0,
        "spec_mismatch": 0,
        "property_fail": 0,
        "runtime_error": 0,
    }
    if fails:
        return {
            "fails": fails,
            "stats": stats,
            "by_function": {c["function"]: False for c in cards},
        }
    it = Interp(spec)
    batch, meta = [], []
    for ex in examples:
        c = cmap[ex["function"]]
        # 設例の入力に datetime.date が入りうる（日付の入力）ので JSON 化してから渡す
        batch.append(
            {
                "function": ex["function"],
                "inputs": casegen.to_json_inputs(ex["inputs"]),
                "date_args": _date_args(c),
                "date_fields": _date_fields(c),
            }
        )
        meta.append((ex.get("kind", "example"), ex))
    for r in spec["rules"]:
        c = cmap.get(r["function"])
        if c is None:
            continue
        for case in casegen.generate(spec, r, c, n_random=n_random, deltas=deltas):
            batch.append(
                {
                    "function": r["function"],
                    "inputs": casegen.to_json_inputs(case["inputs"]),
                    "date_args": _date_args(c),
                    "date_fields": _date_fields(c),
                }
            )
            meta.append(
                (
                    "spec",
                    {"function": r["function"], "inputs": case["inputs"], "kind": case["kind"]},
                )
            )
    got = runner.run_cases(src, batch, timeout=timeout, per_call_timeout=per_call_timeout)
    bad_fns: set[str] = set()
    for (layer, m), g in zip(meta, got):
        fn = m["function"]
        c = cmap[fn]
        if "error" in g:
            stats["runtime_error"] += 1
            if layer == "spec":
                # 仕様から作ったケースで生成コードが例外：インタプリタでも例外なら仕様の誤り（D で直す）、
                # インタプリタが値を返すなら生成器の誤り（I。記録だけ）
                try:
                    want = it.call(fn, **m["inputs"])
                    spec_layer, extra = "interp_vs_code", {"expected": str(want)}
                except Exception as e:  # noqa: BLE001
                    spec_layer, extra = "spec_error", {"interp_msg": f"{type(e).__name__}: {e}"}
                fails.append(
                    {
                        "layer": spec_layer,
                        "function": fn,
                        "inputs": casegen.to_json_inputs(m["inputs"]),
                        "msg": g["error"],
                    }
                    | extra
                )
            else:
                fails.append(
                    {"layer": layer, "function": fn, "inputs": m["inputs"], "msg": g["error"]}
                )
            bad_fns.add(fn)
            continue
        v = g["value"]
        if layer in ("crosscheck", "example") and _norm_expected(m["expected"], c) is _BAD:
            stats["bad_expected"] = (
                stats.get("bad_expected", 0) + 1
            )  # 期待値を解釈できない設例は比べない
            continue
        if layer == "crosscheck":
            stats["cross_total"] = stats.get("cross_total", 0) + 1
            want = _norm_expected(m["expected"], c)
            if v == want:
                stats["cross_pass"] = stats.get("cross_pass", 0) + 1
            else:
                fails.append(
                    {
                        "layer": "crosscheck",
                        "function": fn,
                        "inputs": m["inputs"],
                        "expected": m["expected"],
                        "actual": v if not isinstance(v, dt.date) else v.isoformat(),
                        "work": m.get("work"),
                    }
                )
                bad_fns.add(fn)
            continue
        if layer == "example":
            stats["example_total"] += 1
            want = _norm_expected(m["expected"], c)
            if v is None and any(x is None for x in m["inputs"].values()):
                stats["example_inconclusive"] += 1
            elif v == want:
                stats["example_pass"] += 1
            else:
                fails.append(
                    {
                        "layer": "example",
                        "function": fn,
                        "source": m.get("source"),
                        "inputs": m["inputs"],
                        "expected": m["expected"],
                        "actual": v if not isinstance(v, dt.date) else v.isoformat(),
                    }
                )
                bad_fns.add(fn)
            continue
        stats["spec_cases"] += 1
        try:
            want = it.call(fn, **m["inputs"])
        except Exception as e:  # noqa: BLE001  仕様そのものの誤り（型の取り違えなど）。D に戻す
            stats["runtime_error"] += 1
            fails.append(
                {
                    "layer": "spec_error",
                    "function": fn,
                    "inputs": casegen.to_json_inputs(m["inputs"]),
                    "msg": f"{type(e).__name__}: {e}",
                }
            )
            bad_fns.add(fn)
            continue
        if v != want:
            stats["spec_mismatch"] += 1
            fails.append(
                {
                    "layer": "interp_vs_code",
                    "function": fn,
                    "inputs": casegen.to_json_inputs(m["inputs"]),
                    "expected": str(want),
                    "actual": str(v),
                }
            )
            bad_fns.add(fn)
        elif (
            c["output"]["type"] == "int"
            and c["output"].get("unit") == "JPY"
            and isinstance(v, int)
            and v < 0
        ):
            stats["property_fail"] += 1
            fails.append(
                {
                    "layer": "property",
                    "function": fn,
                    "inputs": casegen.to_json_inputs(m["inputs"]),
                    "msg": f"negative amount {v}",
                }
            )
            bad_fns.add(fn)
    # 失敗の記録は関数ごとに先頭 8 件まで（改修プロンプトを肥大させない）
    trimmed, per = [], {}
    for f in fails:
        k = (f["function"], f["layer"])
        per[k] = per.get(k, 0) + 1
        if per[k] <= 8:
            trimmed.append(f)
    return {
        "fails": trimmed,
        "n_fails": len(fails),
        "stats": stats,
        "by_function": {c["function"]: c["function"] not in bad_fns for c in cards},
    }

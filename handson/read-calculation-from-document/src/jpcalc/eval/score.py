"""正解テストでの採点（評価側だけ）。

データセット同梱の pytest を、テストもケースも変えずに sandbox の別プロセスで実行する。正解の置き場所を汚さないよう、
テストと cases.jsonl を一時ディレクトリへ写して `--impl <評価対象>` で走らせ、JUnit XML からケースの合否を読む。
両コーパスの conftest は `--impl` を受け、テストは `../cases.jsonl` を読む（同じ配置に写せば同じに動く）。
"""

from __future__ import annotations

import collections
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from ..common import sandbox
from .gold import Gold, GoldMismatch

TIMEOUT = 300.0


def run_pytest(g: Gold, impl: Path, *, timeout: float = TIMEOUT) -> dict:
    """impl を正解テストで採点する。戻り値：{case_pass: {case_id: bool}, error, elapsed, returncode}。"""
    v = g.verify()
    if v["unverified"]:
        # 照合値の無い正解で採点しない（照合済みとみなさない）
        raise GoldMismatch(f"{g.doc_id}: 照合値の無い正解がある: {v['unverified'][:3]}")
    with tempfile.TemporaryDirectory(prefix="jpcalc_score_") as tmp:
        t = Path(tmp) / "calc"
        shutil.copytree(g.tests_dir(), t / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(g.cases_file(), t / "cases.jsonl")
        (t / "programs").mkdir()  # 正解プログラムは写さない（評価対象だけを --impl で渡す）
        impl_copy = Path(tmp) / "impl_under_test.py"
        shutil.copy(impl, impl_copy)
        xml = Path(tmp) / "junit.xml"
        r = sandbox.run(
            [
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                str(t / "tests"),
                "--impl",
                str(impl_copy),
                f"--junitxml={xml}",
                "-o",
                "junit_family=xunit2",
            ],
            timeout=timeout,
            cwd=Path(tmp),
        )
        results: dict[str, bool] = {}
        if xml.exists():
            for tc in ET.parse(xml).getroot().iter("testcase"):
                name = tc.get("name", "")
                cid = name[name.index("[") + 1 : -1] if "[" in name else name
                ok = not any(c.tag in ("failure", "error", "skipped") for c in tc)
                # 同じケースが複数のテストにあれば、すべてに合格したときだけ合格
                results[cid] = results.get(cid, True) and ok
    err = None
    if r.timed_out:
        err = "timeout"
    elif not results:
        err = "no_results: " + (r.stderr or r.stdout)[-1500:]
    cases = g.cases()
    missing = [c["case_id"] for c in cases if c["case_id"] not in results]
    if err is None and (r.returncode not in (0, 1) or missing):
        # 一部のテストが収集・実行されなかった（該当のケースは不合格のまま。原因を隠さない）
        err = (
            f"partial: returncode={r.returncode} missing={len(missing)}: "
            + (r.stderr or r.stdout)[-800:]
        )
    out = {c["case_id"]: results.get(c["case_id"], False) for c in cases}
    return {
        "case_pass": out,
        "error": err,
        "elapsed": round(r.elapsed, 2),
        "returncode": r.returncode,
    }


def no_module(g: Gold, reason: str = "no_module") -> dict:
    """生成物が無いときの採点結果（全ケース不合格。分母から外さない）。"""
    return {"case_pass": {c["case_id"]: False for c in g.cases()}, "error": reason}


def placement(units: list[str]) -> str:
    if any(u.startswith("rider_") for u in units):
        return "rider"
    if any(u.startswith("app") for u in units):
        return "appendix"
    return "article"


def summarize(g: Gold, pdf_id: str, run: dict) -> dict:
    """ルール単位・ケース単位の集計。ルールの合格 = そのルールの全ケースに合格。"""
    ak = {r["function"]: r for r in g.answer_key()}
    cs = g.cases()
    by_fn: dict[str, list[tuple[str, bool]]] = collections.defaultdict(list)
    for c in cs:
        by_fn[c["function"]].append((c.get("kind", ""), run["case_pass"][c["case_id"]]))
    rules = []
    for fn, a in ak.items():
        res = by_fn.get(fn, [])
        kinds: collections.Counter = collections.Counter()
        kinds_ok: collections.Counter = collections.Counter()
        for k, ok in res:
            kinds[k] += 1
            kinds_ok[k] += ok
        mods = a.get("modalities") or []
        diff = a.get("difficulty") or {}
        rules.append(
            {
                "pdf_id": pdf_id,
                "function": fn,
                "rule": a.get("rule", fn),
                "pattern": a.get("pattern"),
                "modalities": mods,
                "difficulty": diff,
                "figure_only": mods == ["figure"] or bool(diff.get("figure_only")),
                "placement": placement(a.get("units") or []),
                "n_cases": len(res),
                "n_pass": sum(ok for _, ok in res),
                "passed": bool(res) and all(ok for _, ok in res),
                "by_kind": {k: [kinds_ok[k], kinds[k]] for k in kinds},
            }
        )
    return {
        "pdf_id": pdf_id,
        "rules": rules,
        "error": run["error"],
        "n_cases": len(cs),
        "n_pass": sum(run["case_pass"].values()),
    }

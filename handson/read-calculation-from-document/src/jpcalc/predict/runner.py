"""生成モジュールを sandbox の別プロセスで呼び、結果を返す。

本プロセスに生成コードを import しない。ケースは JSON で渡し、結果も JSON で受け取る。
例外は {"error": "..."} として返す（黙って None にしない）。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..common import sandbox
from .codegen_check import require_ok

# ケースごとの時間制限（argv[4] 秒。0 なら付けない）。時間切れはそのケースだけ {"error": "timeout"} にする
HARNESS = r"""
import datetime, importlib.util, json, signal, sys, traceback
class _CallTimeout(BaseException):
    pass
def _alarm(signum, frame):
    raise _CallTimeout()
per_call = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
if per_call > 0:
    signal.signal(signal.SIGALRM, _alarm)
spec = importlib.util.spec_from_file_location("gen", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cases = json.load(open(sys.argv[2], encoding="utf-8"))
out = []
def enc(v):
    if isinstance(v, datetime.date): return {"__date__": v.isoformat()}
    if v is None or isinstance(v, (bool, int, str)): return v
    try:
        from fractions import Fraction
        if isinstance(v, Fraction): return {"__frac__": [v.numerator, v.denominator]}
    except Exception: pass
    return {"__repr__": repr(v)}
for c in cases:
    kw = {}
    for k, v in c["inputs"].items():
        if k in c.get("date_args", ()) and v is not None:
            v = datetime.date.fromisoformat(v)
        elif k in c.get("date_fields", {}) and isinstance(v, list):
            v = [{f: (datetime.date.fromisoformat(y) if f in c["date_fields"][k] and isinstance(y, str) else y)
                  for f, y in it.items()} if isinstance(it, dict) else it for it in v]
        kw[k] = v
    try:
        if per_call > 0:
            signal.setitimer(signal.ITIMER_REAL, per_call)
        try:
            v = getattr(m, c["function"])(**kw)
        finally:
            if per_call > 0:
                signal.setitimer(signal.ITIMER_REAL, 0)
        out.append({"value": enc(v)})
    except _CallTimeout:
        out.append({"error": "timeout"})
    except Exception as e:
        out.append({"error": f"{type(e).__name__}: {e}"})
json.dump(out, open(sys.argv[3], "w", encoding="utf-8"))
"""


def decode(v):
    import datetime as dt
    from fractions import Fraction

    if isinstance(v, dict):
        if "__date__" in v:
            return dt.date.fromisoformat(v["__date__"])
        if "__frac__" in v:
            return Fraction(*v["__frac__"])
        return v
    return v


def run_cases(
    module_src: str, cases: list[dict], *, timeout: float = 120, per_call_timeout: float = 5
) -> list[dict]:
    """cases: [{function, inputs(JSON 化済み), date_args}] → [{value} | {error}]（順序は同じ）。

    timeout は全ケースの実行の上限（超えれば全ケースが時間切れ）、per_call_timeout は 1 回の呼び出しの上限
    （超えたケースだけが {"error": "timeout"}）。どちらも configs/pipeline.yaml の sandbox から渡す。
    """
    require_ok(module_src)  # 許可リストの外の import・危険な呼び出しがあれば実行しない
    with tempfile.TemporaryDirectory(prefix="jpcalc_run_") as tmp:
        t = Path(tmp)
        (t / "gen.py").write_text(module_src, encoding="utf-8")
        (t / "harness.py").write_text(HARNESS, encoding="utf-8")
        (t / "cases.json").write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
        r = sandbox.run(
            [
                str(t / "harness.py"),
                str(t / "gen.py"),
                str(t / "cases.json"),
                str(t / "out.json"),
                str(per_call_timeout),
            ],
            timeout=timeout,
            cwd=t,
        )
        if r.timed_out:
            return [{"error": "timeout"} for _ in cases]
        if r.returncode != 0 or not (t / "out.json").exists():
            msg = (r.stderr or r.stdout)[-800:]
            return [{"error": f"module_error: {msg}"} for _ in cases]
        out = json.loads((t / "out.json").read_text(encoding="utf-8"))
    return [{"value": decode(o["value"])} if "value" in o else o for o in out]

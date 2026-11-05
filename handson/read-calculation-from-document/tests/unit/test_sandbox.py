"""sandbox と生成コードの静的検査の逆対照：時間制限・ネットワーク遮断・環境変数の除去・禁止 import の拒否。"""

from __future__ import annotations

import pytest

from jpcalc.common import sandbox
from jpcalc.predict import runner
from jpcalc.predict.codegen_check import CodegenCheckError, check_module


def _run(tmp_path, code, **kw):
    p = tmp_path / "x.py"
    p.write_text(code, encoding="utf-8")
    return sandbox.run([str(p)], timeout=kw.pop("timeout", 20), **kw)


def test_timeout(tmp_path):
    r = _run(tmp_path, "while True:\n    pass\n", timeout=1)
    assert r.timed_out and r.returncode is None


def test_network_is_blocked(tmp_path):
    r = _run(tmp_path, "import socket\nsocket.socket()\n")
    assert r.returncode != 0 and "network disabled" in r.stderr
    r = _run(tmp_path, "import socket\nsocket.create_connection(('127.0.0.1', 9))\n")
    assert r.returncode != 0 and "network disabled" in r.stderr


def test_env_is_stripped(tmp_path, monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_CONNECTION_NAME", "x")
    monkeypatch.setenv("JPCALC_DATA_DIR", "/secret")
    monkeypatch.setenv("hf_token", "t")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("SNOWSQL_PWD", "t")
    code = "import os, json\nprint(json.dumps(sorted(os.environ)))\n"
    r = _run(tmp_path, code)
    assert r.returncode == 0
    for k in (
        "SNOWFLAKE_CONNECTION_NAME",
        "JPCALC_DATA_DIR",
        "hf_token",
        "GITHUB_TOKEN",
        "SNOWSQL_PWD",
    ):
        assert k not in r.stdout


@pytest.mark.parametrize(
    "src",
    [
        "import os\n",
        "import subprocess\n",
        "from socket import socket\n",
        "import importlib\n",
        "from . import x\n",
        "def f():\n    return eval('1')\n",
        "def f():\n    return open('/etc/passwd').read()\n",
        "def f():\n    return __import__('os')\n",
        "def f(x):\n    return x.__class__\n",
        "g = getattr\n",
        "def f(x):\n    return type(x).mro()\n",
        "def f(g):\n    return g.gi_frame.f_globals\n",
        "def f(d):\n    return d['__builtins__']\n",
        "def f(:\n",
    ],
)
def test_forbidden_code_is_rejected(src):
    assert check_module(src)


def test_allowed_code_passes():
    src = "from __future__ import annotations\nimport datetime as _dt\nfrom fractions import Fraction\n\n\ndef f(*, a=None):\n    return a\n"
    assert check_module(src) == []


def test_runner_refuses_before_running(tmp_path):
    # 静的検査で落ちるモジュールは sandbox で動かさない（副作用のファイルが作られない）
    marker = tmp_path / "ran"
    src = f"import os\nopen({str(marker)!r}, 'w').write('x')\n\n\ndef f():\n    return 1\n"
    with pytest.raises(CodegenCheckError):
        runner.run_cases(src, [{"function": "f", "inputs": {}, "date_args": []}])
    assert not marker.exists()


def test_per_call_timeout_only_fails_the_slow_case():
    """1 回の呼び出しの時間制限は、遅いケースだけを時間切れにする（ほかのケースの値は返る）。"""
    # 静的検査は while を許さないので、検査を通る形の遅い関数（大きな範囲の内包）で試す
    src = (
        "def fast(*, n=None):\n    return n\n\n\n"
        "def slow(*, n=None):\n    return sum([i for i in range(1000000000)])\n"
    )
    cases = [
        {"function": "fast", "inputs": {"n": 1}, "date_args": []},
        {"function": "slow", "inputs": {"n": 1}, "date_args": []},
        {"function": "fast", "inputs": {"n": 2}, "date_args": []},
    ]
    out = runner.run_cases(src, cases, timeout=60, per_call_timeout=0.5)
    assert out == [{"value": 1}, {"error": "timeout"}, {"value": 2}]

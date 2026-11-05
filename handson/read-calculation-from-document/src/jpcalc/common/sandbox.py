"""生成コードの隔離実行（別プロセス・時間制限・ソケットの無効化・環境変数の許可リスト）。

別プロセスで動かし、時間制限・ソケットの無効化・作業ディレクトリの隔離を行う。環境変数は許可した名前だけを渡す。
これは誤りと事故を防ぐための仕組みで、完全な隔離ではない。ソケットの無効化は sitecustomize で socket.socket を
差し替える方式で、Python レベルの接続だけを止める（C 拡張の直接呼び出し・子プロセス・ファイルの読み取りは止めない）。
生成コードがそれらを使えないことは、実行の前の静的検査（predict.codegen_check）で確かめる。
SPCS ジョブでは外部アクセス統合を付けないので、外のネットワークへは出られない。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

SITECUSTOMIZE = """
import socket as _s
class _NoNet(_s.socket):
    def __init__(self, *a, **k):
        raise PermissionError("network disabled in sandbox")
_s.socket = _NoNet
try:
    import _socket as _ls
    _ls.socket = _NoNet
except Exception:
    pass
_s.create_connection = lambda *a, **k: (_ for _ in ()).throw(PermissionError("network disabled in sandbox"))
"""


# 子プロセスに渡す環境変数（許可リスト。ほかは渡さない。接続・資格情報・トークンの手掛かりを渡さないため）
KEEP_ENV = frozenset(
    {"PATH", "LANG", "LANGUAGE", "TZ", "PYTHONHASHSEED", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT"}
)
KEEP_ENV_PREFIXES = ("LC_",)


@dataclass
class Result:
    returncode: int | None
    stdout: str
    stderr: str
    elapsed: float
    timed_out: bool


def run(
    argv: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    extra_path: list[Path] | None = None,
) -> Result:
    with tempfile.TemporaryDirectory(prefix="jpcalc_sb_") as tmp:
        tmpd = Path(tmp)
        (tmpd / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        # 接続・秘密の手掛かりになる環境変数を渡さない
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in KEEP_ENV or k.upper().startswith(KEEP_ENV_PREFIXES)
        }
        env["PYTHONPATH"] = os.pathsep.join([str(tmpd)] + [str(p) for p in (extra_path or [])])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["HOME"] = str(tmpd)
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                [sys.executable, *argv],
                cwd=str(cwd or tmpd),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return Result(p.returncode, p.stdout, p.stderr, time.monotonic() - t0, False)
        except subprocess.TimeoutExpired as e:
            return Result(
                None,
                (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                (e.stderr or b"").decode() if isinstance(e.stderr, bytes) else (e.stderr or ""),
                time.monotonic() - t0,
                True,
            )

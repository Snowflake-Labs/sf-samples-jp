"""`KEY=VALUE` 形式の設定ファイル（configs/deploy.env・deploy.local.env）の読み込み。

シェルスクリプトも同じファイルを `source` するので、書式はシェルと Python の共通部分に限る：
空行と `#` で始まる行は無視し、`KEY=VALUE` の 1 行 1 項目。値の前後の空白と、値全体を囲む引用符は外す。
"""

from __future__ import annotations

from pathlib import Path


class EnvFileError(ValueError):
    """設定ファイルの書式が不正。"""


def parse_env_text(text: str, *, source: str = "<text>") -> dict[str, str]:
    out: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnvFileError(f"{source}:{lineno}: KEY=VALUE の形でない: {raw!r}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key.isidentifier():
            raise EnvFileError(f"{source}:{lineno}: キー名が不正: {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def read_env_file(path: Path) -> dict[str, str]:
    """ファイルが無ければ空の辞書を返す（deploy.local.env は任意のため）。"""
    if not path.exists():
        return {}
    return parse_env_text(path.read_text(encoding="utf-8"), source=str(path))

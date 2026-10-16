"""ローカル設定の解決（接続名・データの場所）。

接続名は環境変数 `SNOWFLAKE_CONNECTION_NAME` → configs/deploy.local.env の `CONNECTION_NAME` の順で解決し、
どちらも無ければエラーにする（リポジトリに接続名を書かない）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .envfile import read_env_file
from .paths import DEPLOY_LOCAL_ENV

CONNECTION_ENV = "SNOWFLAKE_CONNECTION_NAME"
_PLACEHOLDER_PREFIX = "<"


class LocalSettingError(RuntimeError):
    """ローカル設定が無い・未記入。"""


def lookup_local(
    key: str,
    *,
    env: Mapping[str, str] | None = None,
    local_env_path: Path = DEPLOY_LOCAL_ENV,
) -> str | None:
    """環境変数 → deploy.local.env の順に値を探す。ひな型のプレースホルダ（`<...>`）は未記入とみなす。"""
    env = os.environ if env is None else env
    value = env.get(key) or read_env_file(local_env_path).get(key)
    if not value or value.startswith(_PLACEHOLDER_PREFIX):
        return None
    return value


def resolve_connection_name(
    *,
    env: Mapping[str, str] | None = None,
    local_env_path: Path = DEPLOY_LOCAL_ENV,
) -> str:
    env = os.environ if env is None else env
    value = env.get(CONNECTION_ENV) or read_env_file(local_env_path).get("CONNECTION_NAME")
    if not value or value.startswith(_PLACEHOLDER_PREFIX):
        raise LocalSettingError(
            f"接続名が無い。環境変数 {CONNECTION_ENV} を設定するか、"
            f"{local_env_path.name} の CONNECTION_NAME を記入する（configs/deploy.env.example を参照）"
        )
    return value

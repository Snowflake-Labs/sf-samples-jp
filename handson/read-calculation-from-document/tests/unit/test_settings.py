"""接続名の解決と env ファイルの書式。"""

from __future__ import annotations

import pytest

from jpcalc.common.envfile import EnvFileError, parse_env_text, read_env_file
from jpcalc.common.local_settings import (
    CONNECTION_ENV,
    LocalSettingError,
    lookup_local,
    resolve_connection_name,
)


def test_env_wins_over_local_file(tmp_path):
    f = tmp_path / "deploy.local.env"
    f.write_text("CONNECTION_NAME=from_file\n", encoding="utf-8")
    assert resolve_connection_name(env={CONNECTION_ENV: "from_env"}, local_env_path=f) == "from_env"


def test_local_file_is_second(tmp_path):
    f = tmp_path / "deploy.local.env"
    f.write_text("# コメント\nCONNECTION_NAME='from_file'\n", encoding="utf-8")
    assert resolve_connection_name(env={}, local_env_path=f) == "from_file"


@pytest.mark.parametrize(
    "content", [None, "CONNECTION_NAME=<your_connection>\n", "CONNECTION_NAME=\n"]
)
def test_missing_or_placeholder_stops(tmp_path, content):
    f = tmp_path / "deploy.local.env"
    if content is not None:
        f.write_text(content, encoding="utf-8")
    with pytest.raises(LocalSettingError, match="deploy.env.example"):
        resolve_connection_name(env={CONNECTION_ENV: "<x>"}, local_env_path=f)


def test_lookup_local_skips_placeholders(tmp_path):
    f = tmp_path / "deploy.local.env"
    f.write_text("DATA_ROOT_YAKKAN=/d\n", encoding="utf-8")
    assert (
        lookup_local("DATA_ROOT_YAKKAN", env={"DATA_ROOT_YAKKAN": "<p>"}, local_env_path=f) == "/d"
    )
    assert lookup_local("NOPE", env={}, local_env_path=f) is None


def test_env_text_errors():
    with pytest.raises(EnvFileError):
        parse_env_text("NO_EQUALS_SIGN")
    with pytest.raises(EnvFileError):
        parse_env_text("1BAD=x")
    assert read_env_file(__import__("pathlib").Path("/nonexistent/x.env")) == {}

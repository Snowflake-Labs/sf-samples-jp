from __future__ import annotations

import pytest

from jpdocread.common.envfile import EnvFileError, parse_env_text, read_env_file
from jpdocread.common.local_settings import (
    CONNECTION_ENV,
    LocalSettingError,
    lookup_local,
    resolve_connection_name,
)


class TestParseEnvText:
    def test_reads_pairs_and_skips_comments_and_blanks(self):
        text = "# コメント\n\nA=1\n  B = two words \n"
        assert parse_env_text(text) == {"A": "1", "B": "two words"}

    def test_strips_matching_quotes(self):
        assert parse_env_text("A=\"x y\"\nB='z'") == {"A": "x y", "B": "z"}

    def test_keeps_equals_in_value(self):
        assert parse_env_text("A=b=c") == {"A": "b=c"}

    def test_rejects_line_without_equals(self):
        with pytest.raises(EnvFileError, match="KEY=VALUE"):
            parse_env_text("NOT_A_PAIR")

    def test_rejects_bad_key(self):
        with pytest.raises(EnvFileError, match="キー名"):
            parse_env_text("1BAD=x")

    def test_missing_file_is_empty(self, tmp_path):
        assert read_env_file(tmp_path / "none.env") == {}


class TestConnectionName:
    def test_env_var_wins(self, tmp_path):
        f = tmp_path / "local.env"
        f.write_text("CONNECTION_NAME=from_file\n", encoding="utf-8")
        assert (
            resolve_connection_name(env={CONNECTION_ENV: "from_env"}, local_env_path=f)
            == "from_env"
        )

    def test_falls_back_to_local_file(self, tmp_path):
        f = tmp_path / "local.env"
        f.write_text("CONNECTION_NAME=from_file\n", encoding="utf-8")
        assert resolve_connection_name(env={}, local_env_path=f) == "from_file"

    def test_errors_when_neither(self, tmp_path):
        with pytest.raises(LocalSettingError, match="接続名が無い"):
            resolve_connection_name(env={}, local_env_path=tmp_path / "none.env")

    def test_placeholder_is_not_a_value(self, tmp_path):
        f = tmp_path / "local.env"
        f.write_text("CONNECTION_NAME=<your_connection>\n", encoding="utf-8")
        with pytest.raises(LocalSettingError):
            resolve_connection_name(env={}, local_env_path=f)


class TestLookupLocal:
    def test_env_then_file_then_none(self, tmp_path):
        f = tmp_path / "local.env"
        f.write_text("X=file\nY=<path>\n", encoding="utf-8")
        assert lookup_local("X", env={"X": "env"}, local_env_path=f) == "env"
        assert lookup_local("X", env={}, local_env_path=f) == "file"
        assert lookup_local("Y", env={}, local_env_path=f) is None  # ひな型のまま
        assert lookup_local("Z", env={}, local_env_path=f) is None

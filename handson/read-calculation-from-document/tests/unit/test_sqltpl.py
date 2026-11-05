"""SQL のひな型：値の差し込み・未定義の変数で止まる・文の分割（$$ の中を分けない）・ひな型が名前を直書きしない。"""

from __future__ import annotations

import re

import pytest

from jpcalc.common import sqltpl
from jpcalc.common.names import build_names


def _vals(**kw):
    return sqltpl.variables(build_names("JA_DOC_CALC_"), warehouse_size="XSMALL", **kw)


def test_render_and_missing():
    assert sqltpl.render("USE ROLE <% role_predict %>;", _vals()) == "USE ROLE JA_DOC_CALC_PREDICT;"
    with pytest.raises(sqltpl.SqlTemplateError, match="unknown_var"):
        sqltpl.render("SELECT <% unknown_var %>;", _vals())


def test_user_is_quoted_identifier():
    v = _vals(user='a"b')
    assert v["user"] == '"a""b"'


def test_bad_size_is_rejected():
    with pytest.raises(sqltpl.SqlTemplateError):
        sqltpl.variables(build_names("JA_DOC_CALC_"), warehouse_size="XSMALL; DROP")


def test_split_keeps_dollar_body():
    sql = "-- c\nUSE ROLE R;\nCREATE PROCEDURE P() AS\n$$\nBEGIN\n  SELECT 1;\n  SELECT 2;\nEND;\n$$;\nSELECT 3;\n"
    st = sqltpl.split_statements(sql)
    assert len(st) == 3 and "SELECT 2;" in st[1] and st[2] == "SELECT 3;"


def test_setup_files_render_completely():
    for f in sqltpl.SETUP_FILES:
        out = sqltpl.render_file(f, _vals(user="SOMEONE"))
        assert "<%" not in out
        assert sqltpl.split_statements(out)


def test_sql_files_do_not_hardcode_names():
    # 接頭辞つきの名前・接続名・ユーザー名を SQL のファイルに書かない（すべて <% %> で差し込む）
    for p in sqltpl.all_files():
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"JA_DOC_CALC_|DOCCALC", text), p


def test_empty_user_is_rejected():
    with pytest.raises(sqltpl.SqlTemplateError):
        _vals(user="")

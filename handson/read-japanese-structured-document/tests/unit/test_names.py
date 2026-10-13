from __future__ import annotations

import pytest

from jpdocread.common.names import NamingError, build_names, load_names


def test_repository_names_follow_prefix_rule():
    names = load_names()
    assert names.prefix == "JA_DOC_STRUCTURED_"
    assert names.db == "JA_DOC_STRUCTURED_DB"
    assert names.eval_db == "JA_DOC_STRUCTURED_EVAL_DB"
    for value in names.account_objects().values():
        assert value.startswith(names.prefix)


def test_fully_qualified_names_pick_the_right_database():
    names = build_names("ABC_")
    assert names.fq("schema_ops", "RUNS") == "ABC_DB.ABC_OPS.RUNS"
    assert names.fq("schema_results") == "ABC_EVAL_DB.ABC_RESULTS"
    assert names.fq("schema_gold", "FILES") == "ABC_EVAL_DB.ABC_GOLD.FILES"


@pytest.mark.parametrize("bad", ["abc_", "ABC", "_ABC_", "AB-C_", ""])
def test_rejects_malformed_prefix(bad):
    with pytest.raises(NamingError):
        build_names(bad)


def test_rejects_banned_word_in_prefix():
    with pytest.raises(NamingError, match="snow"):
        build_names("MY_SNOW_")


def test_missing_prefix_in_deploy_env(tmp_path):
    f = tmp_path / "deploy.env"
    f.write_text("WAREHOUSE_SIZE=XSMALL\n", encoding="utf-8")
    with pytest.raises(NamingError, match="NAME_PREFIX"):
        load_names(f)

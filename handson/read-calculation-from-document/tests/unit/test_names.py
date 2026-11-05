"""オブジェクト名の組み立てと命名規則。"""

from __future__ import annotations

import pytest

from jpcalc.common.names import NamingError, build_names, load_names


def test_repo_deploy_env_builds_expected_names():
    n = load_names()
    assert n.prefix == "JA_DOC_CALC_"
    assert (n.db, n.eval_db) == ("JA_DOC_CALC_DB", "JA_DOC_CALC_EVAL_DB")
    assert (n.role_admin, n.role_predict, n.role_eval) == (
        "JA_DOC_CALC_ADMIN",
        "JA_DOC_CALC_PREDICT",
        "JA_DOC_CALC_EVAL_ROLE",
    )
    assert n.image_repository == "JA_DOC_CALC_DB.JA_DOC_CALC_APP.IMAGES"
    assert n.fq("schema_gold", "FILES") == "JA_DOC_CALC_EVAL_DB.JA_DOC_CALC_GOLD.FILES"
    assert n.fq("schema_raw", "PDFS") == "JA_DOC_CALC_DB.JA_DOC_CALC_RAW.PDFS"


def test_every_name_has_prefix():
    n = load_names()
    assert all(v.startswith("JA_DOC_CALC_") for v in n.account_objects().values())


@pytest.mark.parametrize("prefix", ["ja_doc_calc_", "JA_DOC_CALC", "1X_", "MY_SNOW_"])
def test_bad_prefix_rejected(prefix):
    with pytest.raises(NamingError):
        build_names(prefix)


def test_missing_prefix(tmp_path):
    f = tmp_path / "deploy.env"
    f.write_text("WAREHOUSE_SIZE=XSMALL\n", encoding="utf-8")
    with pytest.raises(NamingError, match="NAME_PREFIX"):
        load_names(f)

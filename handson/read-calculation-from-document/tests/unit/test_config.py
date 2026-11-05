"""設定ファイルの型付き読み込み。リポジトリの設定が通り、壊した設定が落ちること。"""

from __future__ import annotations

import copy

import pytest
import yaml

from jpcalc.common.paths import CORPORA, PIPELINE_YAML
from jpcalc.config import (
    UNITS,
    ConfigError,
    load_conventions,
    load_corpus_config,
    load_guard_config,
    load_pipeline_config,
)


def test_repo_configs_load():
    p = load_pipeline_config()
    assert p.llm.temperature == 0
    assert p.selftest.crosscheck_mode == "report"
    assert load_conventions().units == UNITS
    g = load_guard_config()
    assert "jpcalc.eval" in g.forbidden_imports
    for name in ("yakkan", "contract"):
        c = load_corpus_config(name)
        assert c.name == name
        assert len(c.source.huggingface.revision) == 40
        assert c.paths.pdf.endswith(".pdf")
    assert load_corpus_config("contract").harness.calendar is True
    assert load_corpus_config("yakkan").harness.calendar is False


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _corpus(name="yakkan"):
    return yaml.safe_load((CORPORA / f"{name}.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "rev", ["main", "v1.0", "f6d368a", "F6D368A6BF84C7EB14A6FBA158E8BFC504FE5366"]
)
def test_unpinned_revision_rejected(tmp_path, rev):
    d = _corpus()
    d["source"]["huggingface"]["revision"] = rev
    _write(tmp_path, "yakkan.yaml", d)
    with pytest.raises(ConfigError, match="40 桁"):
        load_corpus_config("yakkan", tmp_path)


def test_unknown_key_rejected(tmp_path):
    d = _corpus()
    d["paths"]["extra_gold"] = "x"
    _write(tmp_path, "yakkan.yaml", d)
    with pytest.raises(ConfigError, match="extra"):
        load_corpus_config("yakkan", tmp_path)


def test_non_pdf_predict_path_rejected(tmp_path):
    d = _corpus("contract")
    d["paths"]["pdf"] = "inputs/{doc_id}/contract.json"
    _write(tmp_path, "contract.yaml", d)
    with pytest.raises(ConfigError, match="PDF"):
        load_corpus_config("contract", tmp_path)


def test_name_must_match_file(tmp_path):
    _write(tmp_path, "contract.yaml", _corpus("yakkan"))
    with pytest.raises(ConfigError, match="name"):
        load_corpus_config("contract", tmp_path)


def test_unknown_corpus():
    with pytest.raises(ConfigError, match="未知のコーパス"):
        load_corpus_config("novel")


def _pipeline():
    return yaml.safe_load(PIPELINE_YAML.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("llm", "model"), "x'; DROP TABLE t; --", "モデル名"),
        (("selftest", "crosscheck_mode"), "repair", "crosscheck_mode"),
        (("repair", "max_iter"), -1, "max_iter"),
        (("llm", "max_tokens", "k_cards"), 0, "k_cards"),
    ],
)
def test_bad_pipeline_values(tmp_path, path, value, match):
    d = copy.deepcopy(_pipeline())
    cur = d
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    with pytest.raises(ConfigError, match=match):
        load_pipeline_config(_write(tmp_path, "pipeline.yaml", d))


def test_pilot_and_shots_must_be_disjoint(tmp_path):
    d = _pipeline()
    d["slices"]["yakkan"] = {"pilot": ["a--s"], "shots": ["a--s"]}
    with pytest.raises(ConfigError, match="重なって"):
        load_pipeline_config(_write(tmp_path, "pipeline.yaml", d))


def test_units_must_match_d007(tmp_path):
    from jpcalc.common.paths import CONVENTIONS_YAML

    d = yaml.safe_load(CONVENTIONS_YAML.read_text(encoding="utf-8"))
    d["units"] = [*d["units"], "RATE"]
    with pytest.raises(ConfigError, match="単位の語彙"):
        load_conventions(_write(tmp_path, "conventions.yaml", d))


def test_guard_allow_list_pdf_only(tmp_path):
    from jpcalc.common.paths import GUARD_YAML

    d = yaml.safe_load(GUARD_YAML.read_text(encoding="utf-8"))
    d["predict_allow"]["yakkan"].append("documents/*/policy.json")
    with pytest.raises(ConfigError, match="PDF だけ"):
        load_guard_config(_write(tmp_path, "guard.yaml", d))


def test_missing_and_broken_yaml(tmp_path):
    with pytest.raises(ConfigError, match="無い"):
        load_pipeline_config(tmp_path / "none.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        load_pipeline_config(bad)


def test_slices_need_both_corpora(tmp_path):
    d = _pipeline()
    del d["slices"]["contract"]
    with pytest.raises(ConfigError, match="slices"):
        load_pipeline_config(_write(tmp_path, "pipeline.yaml", d))


@pytest.mark.parametrize(("section", "key"), [("index", "records"), ("columns", "pdf_file")])
def test_nullable_index_keys_must_be_explicit(tmp_path, section, key):
    d = _corpus()
    target = d["index"] if section == "index" else d["index"]["columns"]
    del target[key]
    _write(tmp_path, "yakkan.yaml", d)
    with pytest.raises(ConfigError, match=key):
        load_corpus_config("yakkan", tmp_path)


@pytest.mark.parametrize(
    ("key", "value"),
    [("strict_dir_names", ["calc/"]), ("boundary_dir_parts", ["tests"])],
)
def test_guard_dir_shapes(tmp_path, key, value):
    from jpcalc.common.paths import GUARD_YAML

    d = yaml.safe_load(GUARD_YAML.read_text(encoding="utf-8"))
    d[key] = value
    with pytest.raises(ConfigError, match=key):
        load_guard_config(_write(tmp_path, "guard.yaml", d))

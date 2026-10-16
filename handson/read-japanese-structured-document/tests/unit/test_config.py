from __future__ import annotations

import pytest
import yaml
from fixtures.configs import corpus_dict

from jpdocread.config import (
    ConfigError,
    CorpusConfig,
    available_corpora,
    expand_vars,
    load_corpus_config,
    load_pipeline_config,
)


class TestRepositoryConfigs:
    def test_both_corpora_are_available(self):
        assert available_corpora() == ["contract", "yakkan"]

    @pytest.mark.parametrize("name", ["contract", "yakkan"])
    def test_corpus_loads_and_is_consistent(self, name):
        cfg = load_corpus_config(name)
        assert cfg.name == name
        assert len(cfg.figure_shots) == 2
        assert set(cfg.figure_shots) <= set(cfg.eval_excluded)
        assert len(cfg.slices["pilot"]) == 10

    def test_features_differ_by_corpus(self):
        assert load_corpus_config("contract").features.parties is True
        assert load_corpus_config("yakkan").features.parties is False

    def test_pipeline_loads(self):
        cfg = load_pipeline_config()
        assert cfg.figure.model
        assert cfg.defaults.slice == "pilot"
        assert "all" in cfg.defaults.confirm_slices

    def test_unknown_corpus_lists_choices(self):
        with pytest.raises(ConfigError, match="選べるもの"):
            load_corpus_config("nope")


class TestCorpusValidation:
    def test_rejects_unknown_key(self):
        with pytest.raises(ValueError, match="extra"):
            CorpusConfig.model_validate(corpus_dict(unexpected=1))

    def test_rejects_wrong_type(self):
        with pytest.raises(ValueError):
            CorpusConfig.model_validate(corpus_dict(figure_shots="not-a-list"))

    def test_rejects_unknown_builder(self):
        with pytest.raises(ValueError):
            CorpusConfig.model_validate(corpus_dict(structure_builder="ocr"))

    def test_rejects_all_slice_in_config(self):
        with pytest.raises(ValueError, match="manifest"):
            CorpusConfig.model_validate(corpus_dict(slices={"all": ["x"]}))

    def test_rejects_donor_not_excluded(self):
        with pytest.raises(ValueError, match="figure_shots"):
            CorpusConfig.model_validate(corpus_dict(eval_excluded=["aaa-0001--style-a"]))

    def test_rejects_excluded_doc_in_pilot(self):
        with pytest.raises(ValueError, match="pilot"):
            CorpusConfig.model_validate(corpus_dict(slices={"pilot": ["aaa-0001--style-a"]}))

    def test_rejects_duplicate_in_slice(self):
        with pytest.raises(ValueError, match="重複"):
            CorpusConfig.model_validate(corpus_dict(slices={"x": ["a", "a"]}))

    def test_name_must_match_file(self, tmp_path):
        (tmp_path / "foo.yaml").write_text(
            yaml.safe_dump(corpus_dict(name="bar")), encoding="utf-8"
        )
        with pytest.raises(ConfigError, match="一致しない"):
            load_corpus_config("foo", corpora_dir=tmp_path)


class TestExpandVars:
    def test_expands_from_env_then_file(self, tmp_path):
        f = tmp_path / "local.env"
        f.write_text("ROOT=/from/file\n", encoding="utf-8")
        assert expand_vars("${ROOT}/x", env={}, local_env_path=f) == "/from/file/x"
        assert expand_vars("${ROOT}/x", env={"ROOT": "/env"}, local_env_path=f) == "/env/x"

    def test_unset_var_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError, match="未設定"):
            expand_vars("${NOPE}", env={}, local_env_path=tmp_path / "none.env")

    def test_text_without_vars_is_unchanged(self, tmp_path):
        assert expand_vars("/plain", env={}, local_env_path=tmp_path / "x") == "/plain"

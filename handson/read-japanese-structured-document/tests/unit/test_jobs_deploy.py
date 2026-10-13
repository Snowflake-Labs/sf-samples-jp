"""Snowflake を使わずに検査できる、ジョブと配置の規則（jobs.py・deploy.py・cli の names）。

Snowflake 上の振る舞い（ステップの成否・キャッシュ・ロール分離）は検証用接続で確かめる。
"""

from __future__ import annotations

import copy

import pytest

from jpdocread import deploy, jobs

BASE = {
    "schema_version": "1.2",
    "doc_id": "x",
    "meta": {},
    "pages": [{"number": 1, "text": ""}],
    "outline": [],
    "elements": [
        {
            "element_id": "e1",
            "node_kind": "paragraph",
            "citation": "第1条",
            "text": "t",
            "pages": [1],
        }
    ],
    "tables": [],
    "figures": [],
    "refs": [],
    "repair_queue": [],
    "provenance": {},
    "numbering_scheme": None,
    "parties": [],
    "defined_terms": [],
    "defined_terms_detail": [],
}


class TestValidateOutput:
    def test_yakkan_shape_passes(self):
        jobs.validate_output(BASE)

    def test_contract_shape_passes(self):
        out = {
            **BASE,
            "numbering_scheme": "contract-standard",
            "parties": [{"alias": "甲", "name": "株式会社ア"}],
        }
        jobs.validate_output(out)

    @pytest.mark.parametrize("key", [*jobs.REQUIRED_KEYS, *jobs.CONTRACT_KEYS])
    def test_missing_key_is_rejected(self, key):
        out = {k: v for k, v in BASE.items() if k != key}
        with pytest.raises(ValueError, match=key):
            jobs.validate_output(out)

    def test_wrong_schema_version_is_rejected(self):
        with pytest.raises(ValueError, match="schema_version"):
            jobs.validate_output({**BASE, "schema_version": "1.1"})

    def test_element_without_citation_is_rejected(self):
        out = copy.deepcopy(BASE)
        del out["elements"][0]["citation"]
        with pytest.raises(ValueError, match="citation"):
            jobs.validate_output(out)

    def test_contract_party_without_name_is_rejected(self):
        out = {**BASE, "numbering_scheme": "contract-standard", "parties": [{"alias": "甲"}]}
        with pytest.raises(ValueError, match="alias / name"):
            jobs.validate_output(out)


class TestFailInjected:
    def test_matches_exact_step_and_doc(self):
        with pytest.raises(RuntimeError, match="S50:d1"):
            jobs.fail_injected("S50", "d1", "S20:d9, S50:d1")

    @pytest.mark.parametrize("spec", ["", "S30:d1", "S50:d10", "S50:d", ",,"])
    def test_does_not_match_other_steps_or_prefixes(self, spec):
        jobs.fail_injected("S50", "d1", spec)  # 例外を出さない


class TestLedger:
    def _row(self, doc_id: str, md5: str) -> deploy.LedgerRow:
        return deploy.LedgerRow(
            "contract", doc_id, f"contract/{doc_id}/doc.pdf", 1, md5, "s", 1, 1.0, 1.0, "v"
        )

    def test_stage_matching_md5_is_ok(self):
        rows = [self._row("a", "m1"), self._row("b", "m2")]
        assert (
            deploy.stage_mismatches(rows, {"contract/a/doc.pdf": "m1", "contract/b/doc.pdf": "m2"})
            == []
        )

    def test_missing_or_different_md5_is_reported(self):
        rows = [self._row("a", "m1"), self._row("b", "m2")]
        assert deploy.stage_mismatches(rows, {"contract/a/doc.pdf": "zz"}) == [
            "contract/a/doc.pdf",
            "contract/b/doc.pdf",
        ]

    def test_ledger_rows_use_corpus_prefixed_paths(self, tmp_path):
        from fixtures.configs import make_corpus_cfg, make_pipeline_cfg
        from fixtures.synthetic_dataset import SyntheticDoc, build_dataset
        from fixtures.synthetic_pdf import YAKKAN_PAGES

        from jpdocread.fetch.pipeline import run_fetch
        from jpdocread.fetch.sources import LocalSource

        d = "synth-0001--syn-a4-1col"
        ds = build_dataset(
            tmp_path / "src", [SyntheticDoc(d, "synth-0001", pages=2, pdf_pages=YAKKAN_PAGES)]
        )
        corpus = make_corpus_cfg(figure_shots=[], eval_excluded=[], slices={"pilot": [d]})
        fetched = run_fetch(LocalSource(ds), corpus, make_pipeline_cfg(), tmp_path / "data",
                            docs=None, docs_file=None, slice_name="pilot")  # fmt: skip
        [row] = deploy.ledger_rows(fetched, corpus.name)
        assert row.rel_path == f"{corpus.name}/{d}/doc.pdf"
        assert (row.n_pages, round(row.page_w_pt)) == (2, 595)
        assert row.md5 == deploy.md5_file(fetched.dataset_dir / d / "doc.pdf")


class TestRegisterRunValidation:
    @pytest.mark.parametrize("run_id", ["", "a b", "x'; DROP TABLE t; --", "a" * 129])
    def test_bad_run_id_is_rejected_before_connecting(self, run_id, corpus_cfg):
        with pytest.raises(deploy.DeployError, match="run_id"):
            deploy.register_run(run_id=run_id, corpus=corpus_cfg, doc_ids=["d"], slice_name="pilot",
                                image_tag="t1", dataset_version=None)  # fmt: skip

    def test_bad_image_tag_is_rejected_before_connecting(self, corpus_cfg):
        with pytest.raises(deploy.DeployError, match="image_tag"):
            deploy.register_run(run_id="r1", corpus=corpus_cfg, doc_ids=["d"], slice_name="pilot",
                                image_tag="t;x", dataset_version=None)  # fmt: skip


class TestDeployItems:
    def test_items_are_shell_and_sql_safe(self):
        from jpdocread.cli import DEPLOY_SETTINGS, deploy_items

        items = deploy_items()
        assert set(DEPLOY_SETTINGS) <= set(items)
        assert all(k.isupper() and v.replace("_", "").isalnum() for k, v in items.items())
        assert items["DB"].startswith(items["NAME_PREFIX"])

    def test_unsafe_setting_is_rejected(self, tmp_path, monkeypatch):
        from jpdocread import cli
        from jpdocread.config import ConfigError

        bad = tmp_path / "deploy.env"
        bad.write_text(
            "NAME_PREFIX=P_\n"
            + "\n".join(f"{k}=X" for k in cli.DEPLOY_SETTINGS)
            + "\nIMAGE_NAME=a;b\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(cli.paths, "DEPLOY_ENV", bad)
        from jpdocread.common.names import load_names

        monkeypatch.setattr(cli, "load_names", lambda: load_names(bad))
        with pytest.raises(ConfigError, match="IMAGE_NAME"):
            cli.deploy_items()


class TestReviewFixes:
    def test_donor_in_targets_is_rejected_before_connecting(self):
        from jpdocread.config import load_corpus_config

        c = load_corpus_config("contract")
        with pytest.raises(deploy.DeployError, match="供出元"):
            deploy.register_run(run_id="r1", corpus=c, doc_ids=[c.figure_shots[0]], slice_name="pilot",
                                image_tag="20261009000000", dataset_version=None)  # fmt: skip

    @pytest.mark.parametrize("tag", ["latest", "a b", "x'y"])
    def test_image_tag_rule_matches_run_job(self, tag, corpus_cfg):
        with pytest.raises(deploy.DeployError, match="image_tag"):
            deploy.register_run(run_id="r1", corpus=corpus_cfg, doc_ids=["d"], slice_name="pilot",
                                image_tag=tag, dataset_version=None)  # fmt: skip

    def test_put_path_rejects_single_quote(self, tmp_path):
        bad = tmp_path / "a'b.pdf"
        with pytest.raises(deploy.DeployError, match="'"):
            deploy._put_path(bad)
        assert deploy._put_path(tmp_path / "ok.pdf").endswith("ok.pdf")

from __future__ import annotations

import json

import pytest
from fixtures.synthetic_dataset import DEFAULT_DOCS, build_dataset

from jpdocread.fetch.pipeline import FETCH_RECORD, execute_fetch, plan_fetch, run_fetch
from jpdocread.fetch.sources import FetchError, LocalSource
from jpdocread.fetch.verify import VerificationError


def test_fetch_predict_files_only(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    data_dir = tmp_path / "data"
    res = run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, data_dir, slice_name="two")
    assert res.dataset_dir == data_dir / "testcorpus" / "vtest"
    assert res.files == ("doc.pdf",)
    for d in ("aaa-0001--style-a", "bbb-0001--style-a"):
        assert (res.dataset_dir / d / "doc.pdf").exists()
        assert not (res.dataset_dir / d / "answer.json").exists()
    assert (res.dataset_dir / "manifest.json").exists()
    assert not (data_dir / "testcorpus" / "_index").exists()
    assert res.report.summary() == {"verified": 2, "unverified": 0}

    record = json.loads((res.dataset_dir / FETCH_RECORD).read_text(encoding="utf-8"))
    assert record["dataset_version"] == "vtest"
    assert record["selection"]["doc_ids"] == ["aaa-0001--style-a", "bbb-0001--style-a"]
    assert record["source"]["kind"] == "local"


def test_fetch_with_gold(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    res = run_fetch(
        LocalSource(dataset),
        corpus_cfg,
        pipeline_cfg,
        tmp_path,
        docs="bbb-0001--style-a",
        with_gold=True,
    )
    assert set(res.files) == {
        "doc.pdf",
        "answer.json",
        "elements.jsonl",
        "source.json",
        "layout.json",
        "qa.json",
    }
    assert (res.dataset_dir / "bbb-0001--style-a" / "elements.jsonl").exists()
    assert res.report.summary()["verified"] == 6


def test_plan_writes_nothing_to_the_dataset_dir(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    plan = plan_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    assert plan.selection.doc_ids == ("bbb-0001--style-a",)
    assert not plan.dataset_dir.exists()
    plan.discard()
    assert list((tmp_path / "testcorpus").iterdir()) == []


class CountingSource(LocalSource):
    def __init__(self, root):
        super().__init__(root)
        self.index_calls = 0

    def fetch_index(self, dest):
        self.index_calls += 1
        return super().fetch_index(dest)


def test_execute_reuses_the_planned_index(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    src = CountingSource(dataset)
    plan = plan_fetch(src, corpus_cfg, pipeline_cfg, tmp_path)
    # 計画のあとで取得元の manifest が変わっても、確認した計画のまま実行する
    (dataset / "manifest.json").write_text("{}", encoding="utf-8")
    res = execute_fetch(plan)
    assert src.index_calls == 1
    assert res.selection.doc_ids == ("bbb-0001--style-a",)


def test_same_version_with_different_manifest_stops(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    other = build_dataset(tmp_path / "other", DEFAULT_DOCS[:3])  # 版名は同じ vtest、中身が違う
    with pytest.raises(FetchError, match="中身の違う"):
        run_fetch(LocalSource(other), corpus_cfg, pipeline_cfg, tmp_path)


REV_A = "a" * 40
REV_B = "b" * 40


def _hub_source(root, revision):
    from test_sources import FakeHub

    from jpdocread.fetch.sources import HuggingFaceSource

    return HuggingFaceSource("org/repo", revision, downloader=FakeHub(root))


def test_same_version_from_another_source_goes_to_another_dir(
    dataset, tmp_path, corpus_cfg, pipeline_cfg
):
    # 約款の実例：手元（local）と HF で版名は同じ v7、manifest の中身が違う
    local = run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    other = build_dataset(tmp_path / "other", DEFAULT_DOCS[:3])  # 版名は同じ vtest、中身が違う
    hub = run_fetch(_hub_source(other, REV_A), corpus_cfg, pipeline_cfg, tmp_path)
    assert local.dataset_dir == tmp_path / "testcorpus" / "vtest"
    assert hub.dataset_dir == tmp_path / "testcorpus" / f"vtest-hf-{REV_A[:12]}"
    assert (local.dataset_dir / "manifest.json").read_bytes() != (
        hub.dataset_dir / "manifest.json"
    ).read_bytes()
    record = json.loads((hub.dataset_dir / FETCH_RECORD).read_text(encoding="utf-8"))
    assert record["source"] == {"kind": "huggingface", "repo_id": "org/repo", "revision": REV_A}


def test_same_hub_revision_with_different_manifest_still_stops(
    dataset, tmp_path, corpus_cfg, pipeline_cfg
):
    # 取得元ごとに分けても、同じ置き場所に中身の違う manifest が来たら従来どおり止める
    run_fetch(_hub_source(dataset, REV_A), corpus_cfg, pipeline_cfg, tmp_path)
    other = build_dataset(tmp_path / "other", DEFAULT_DOCS[:3])
    with pytest.raises(FetchError, match="中身の違う"):
        run_fetch(_hub_source(other, REV_A), corpus_cfg, pipeline_cfg, tmp_path)
    # revision が違えば別の場所なので通る
    run_fetch(_hub_source(other, REV_B), corpus_cfg, pipeline_cfg, tmp_path)


def test_stale_sha256sums_is_removed(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    res = run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    assert (res.dataset_dir / "SHA256SUMS").exists()
    (dataset / "SHA256SUMS").unlink()  # 取得元から消えた索引は、取得先にも残さない
    res = run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    assert not (res.dataset_dir / "SHA256SUMS").exists()


def test_tampered_source_fails_and_writes_no_record(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    (dataset / "bbb-0001--style-a" / "doc.pdf").write_text("x", encoding="utf-8")
    with pytest.raises(VerificationError):
        run_fetch(LocalSource(dataset), corpus_cfg, pipeline_cfg, tmp_path)
    assert not (tmp_path / "testcorpus" / "vtest" / FETCH_RECORD).exists()


def test_refetch_is_idempotent(dataset, tmp_path, corpus_cfg, pipeline_cfg):
    src = LocalSource(dataset)
    a = run_fetch(src, corpus_cfg, pipeline_cfg, tmp_path)
    b = run_fetch(src, corpus_cfg, pipeline_cfg, tmp_path)
    assert a.dataset_dir == b.dataset_dir
    assert b.report.summary() == a.report.summary()

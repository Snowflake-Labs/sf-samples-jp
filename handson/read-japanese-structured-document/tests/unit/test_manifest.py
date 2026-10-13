from __future__ import annotations

import json

import pytest
from fixtures.synthetic_dataset import DEFAULT_DOCS, build_dataset

from jpdocread.fetch.manifest import (
    ManifestError,
    load_manifest,
    load_sha256sums,
    sha256_file,
)


def test_reads_documents_and_version(dataset):
    m = load_manifest(dataset / "manifest.json")
    assert m.version == "vtest"
    assert m.ready_ids() == ["aaa-0001--style-a", "aaa-0001--style-b", "bbb-0001--style-a"]
    assert m.documents["aaa-0001--style-b"].pages == 5


def test_version_falls_back_to_manifest_hash(tmp_path):
    root = build_dataset(tmp_path, DEFAULT_DOCS, dataset_version=None)
    m = load_manifest(root / "manifest.json")
    assert m.version == "sha-" + sha256_file(root / "manifest.json")[:12]


def test_missing_manifest(tmp_path):
    with pytest.raises(ManifestError, match="無い"):
        load_manifest(tmp_path / "manifest.json")


def test_malformed_manifest(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"documents": [{"doc_id": "x"}]}), encoding="utf-8")
    with pytest.raises(ManifestError, match="形"):
        load_manifest(p)


def test_sha256sums_parsing(dataset, tmp_path):
    sums = load_sha256sums(dataset / "SHA256SUMS")
    assert sums["aaa-0001--style-a/elements.jsonl"] == sha256_file(
        dataset / "aaa-0001--style-a" / "elements.jsonl"
    )
    assert load_sha256sums(tmp_path / "none") == {}
    bad = tmp_path / "bad"
    bad.write_text("nothex  x\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_sha256sums(bad)


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", ".hidden", "a..b", "", "x y"])
def test_rejects_unsafe_doc_id(tmp_path, bad):
    p = tmp_path / "manifest.json"
    doc = {"doc_id": bad, "content_id": "c", "status": "ready", "pages": 1}
    p.write_text(json.dumps({"documents": [doc]}), encoding="utf-8")
    with pytest.raises(ManifestError, match="使えない文字"):
        load_manifest(p)


def test_accepts_dataset_style_doc_ids(dataset):
    m = load_manifest(dataset / "manifest.json")
    assert "aaa-0001--style-a" in m.documents

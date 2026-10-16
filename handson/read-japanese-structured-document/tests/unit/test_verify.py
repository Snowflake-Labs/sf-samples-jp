from __future__ import annotations

import pytest
from fixtures.synthetic_dataset import DEFAULT_DOCS, build_dataset

from jpdocread.fetch.manifest import load_manifest, load_sha256sums
from jpdocread.fetch.verify import VerificationError, verify_files

ALL_FILES = ("doc.pdf", "answer.json", "elements.jsonl", "source.json", "layout.json", "qa.json")
READY = ["aaa-0001--style-a", "bbb-0001--style-a"]


def _verify(root, doc_ids=READY, files=ALL_FILES):
    m = load_manifest(root / "manifest.json")
    return verify_files(root, m, load_sha256sums(root / "SHA256SUMS"), doc_ids, files)


def test_all_match_using_manifest_and_sha256sums(dataset):
    report = _verify(dataset)
    # doc.pdf 等は manifest、elements.jsonl は SHA256SUMS で照合される
    assert len(report.verified) == 2 * len(ALL_FILES)
    assert report.unverified == []


def test_file_without_expected_value_is_reported_as_unverified(tmp_path):
    root = build_dataset(tmp_path, DEFAULT_DOCS, with_sha256sums=False)
    report = _verify(root)
    assert report.unverified == [f"{d}/elements.jsonl" for d in READY]


def test_detects_one_byte_change(dataset):
    p = dataset / "aaa-0001--style-a" / "doc.pdf"
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(VerificationError, match="SHA-256 が一致しない") as e:
        _verify(dataset)
    assert e.value.problems == ["aaa-0001--style-a/doc.pdf: SHA-256 が一致しない"]


def test_detects_change_in_sha256sums_only_file(dataset):
    p = dataset / "bbb-0001--style-a" / "elements.jsonl"
    p.write_text("改ざん", encoding="utf-8")
    with pytest.raises(VerificationError, match="elements.jsonl"):
        _verify(dataset)


def test_detects_missing_file(dataset):
    (dataset / "bbb-0001--style-a" / "layout.json").unlink()
    with pytest.raises(VerificationError, match="ファイルが無い"):
        _verify(dataset)


def test_rejects_not_ready_and_unknown(dataset):
    with pytest.raises(VerificationError) as e:
        _verify(dataset, doc_ids=["ccc-0001--style-a", "zzz"], files=("doc.pdf",))
    assert any("ready でない" in p for p in e.value.problems)
    assert any("manifest に無い" in p for p in e.value.problems)


def test_lists_every_problem_not_just_the_first(dataset):
    for d in READY:
        (dataset / d / "doc.pdf").write_text("x", encoding="utf-8")
    with pytest.raises(VerificationError) as e:
        _verify(dataset, files=("doc.pdf",))
    assert len(e.value.problems) == 2

"""pdoc の入口：照合済みの PDF だけを読む（照合していない・差し替えた・記録に無い PDF で止まる）。"""

from __future__ import annotations

import json

import pytest
from fixtures.synthetic_pdf import build_pdf, contract_pages, yakkan_pages

from jpcalc.fetch.run import FETCH_RECORD
from jpcalc.fetch.verify import sha256_file
from jpcalc.pdfread.run import PdocError, make_pdocs


def _corpus(tmp_path, verify="verified"):
    root = tmp_path / "corpus"
    pdfs = {}
    for pid, pages in (("doc-0001--a", yakkan_pages()), ("ct-0001--a", contract_pages())):
        rel = f"files/{pid}.pdf"
        p = build_pdf(root / rel, pages)
        pdfs[pid] = {
            "pdf_id": pid,
            "local_path": rel,
            "sha256_actual": sha256_file(p),
            "verify": verify,
        }
    (root / FETCH_RECORD).write_text(json.dumps({"pdfs": pdfs}), encoding="utf-8")
    return root


def test_make_pdocs(tmp_path):
    root = _corpus(tmp_path)
    res = make_pdocs(root, ["doc-0001--a", "ct-0001--a"], tmp_path / "out")
    assert [(r.pdf_id, r.n_articles, r.n_read_errors) for r in res] == [
        ("doc-0001--a", 3, 0),
        ("ct-0001--a", 3, 0),
    ]
    doc = json.loads((tmp_path / "out" / "ct-0001--a.json").read_text(encoding="utf-8"))
    assert doc["pdoc"]["pdf_id"] == "ct-0001--a"


def test_unverified_is_refused(tmp_path):
    root = _corpus(tmp_path, verify="unverified")
    with pytest.raises(PdocError, match="照合済みでない"):
        make_pdocs(root, ["doc-0001--a"], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_tampered_is_refused(tmp_path):
    root = _corpus(tmp_path)
    (root / "files" / "doc-0001--a.pdf").write_bytes(b"tampered")
    with pytest.raises(PdocError, match="一致しません"):
        make_pdocs(root, ["ct-0001--a", "doc-0001--a"], tmp_path / "out")
    # 1 件でも一致しなければ何も書かない
    assert not (tmp_path / "out").exists()


def test_unknown_and_missing_record(tmp_path):
    root = _corpus(tmp_path)
    with pytest.raises(PdocError, match="取得の記録に無い"):
        make_pdocs(root, ["nope-0001--a"], tmp_path / "out")
    with pytest.raises(PdocError, match="取得の記録がありません"):
        make_pdocs(tmp_path / "empty", ["doc-0001--a"], tmp_path / "out")


def test_build_failure_writes_nothing(tmp_path, monkeypatch):
    # 逆対照：2 件目の読み取りで失敗したら、1 件目も書かない
    import jpcalc.pdfread.run as run

    root = _corpus(tmp_path)
    real = run.build

    def flaky(pid, path):
        if pid == "ct-0001--a":
            raise RuntimeError("boom")
        return real(pid, path)

    monkeypatch.setattr(run, "build", flaky)
    with pytest.raises(RuntimeError):
        make_pdocs(root, ["doc-0001--a", "ct-0001--a"], tmp_path / "out")
    assert not (tmp_path / "out").exists()

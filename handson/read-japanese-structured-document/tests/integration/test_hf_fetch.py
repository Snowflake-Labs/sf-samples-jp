"""Hugging Face からの実取得（設定どおりの repo・revision で、索引と 1 文書を取り、manifest と照合する）。

既定の pytest では走らせない（`uv run pytest -m network`）。データは一時ディレクトリに置き、data/ を汚さない。
"""

from __future__ import annotations

import pytest

from jpdocread.config import load_corpus_config, load_pipeline_config
from jpdocread.fetch.pipeline import run_fetch
from jpdocread.fetch.sources import make_source

pytestmark = pytest.mark.network

# 各コーパスの pilot から、ページ数の少ない 1 文書
DOCS = {"contract": "nda-0003--ct-a4-1col-form", "yakkan": "auto-0001--nl-a4-2col-mincho"}


@pytest.mark.parametrize("name", sorted(DOCS))
def test_fetch_one_doc_from_hub_and_verify(name, tmp_path):
    corpus = load_corpus_config(name)
    res = run_fetch(
        make_source(corpus),
        corpus,
        load_pipeline_config(),
        tmp_path,
        docs=DOCS[name],
        with_gold=True,
    )
    assert res.dataset_dir.name.endswith(f"-hf-{corpus.source.huggingface.revision[:12]}")
    assert res.report.summary()["verified"] >= 5
    got = {
        p.relative_to(res.dataset_dir).as_posix() for p in res.dataset_dir.rglob("*") if p.is_file()
    }
    got = {p for p in got if not p.startswith(".cache/")}
    # 対象の 1 文書と索引だけを取り、ページ画像などは取らない
    assert all(p.startswith(DOCS[name] + "/") or "/" not in p for p in got)
    assert not any(p.endswith(".png") for p in got)

from __future__ import annotations

import pytest

from jpdocread.fetch.manifest import load_manifest
from jpdocread.fetch.select import (
    SelectionError,
    estimate_credits,
    read_docs_file,
    select_docs,
)


@pytest.fixture
def manifest(dataset):
    return load_manifest(dataset / "manifest.json")


def test_default_is_pilot_slice(manifest, corpus_cfg, pipeline_cfg):
    sel = select_docs(manifest, corpus_cfg, pipeline_cfg)
    assert sel.how == "slice:pilot"
    assert sel.doc_ids == ("bbb-0001--style-a",)
    assert not sel.needs_confirmation


def test_all_slice_is_ready_docs_and_needs_confirmation(manifest, corpus_cfg, pipeline_cfg):
    sel = select_docs(manifest, corpus_cfg, pipeline_cfg, slice_name="all")
    assert sel.doc_ids == ("aaa-0001--style-a", "aaa-0001--style-b", "bbb-0001--style-a")
    assert sel.needs_confirmation
    assert sel.eval_excluded == ("aaa-0001--style-a", "aaa-0001--style-b")
    assert sel.pages == 4 + 5 + 2


def test_named_slice(manifest, corpus_cfg, pipeline_cfg):
    sel = select_docs(manifest, corpus_cfg, pipeline_cfg, slice_name="two")
    assert sel.doc_ids == ("aaa-0001--style-a", "bbb-0001--style-a")


def test_docs_arg_keeps_order_and_dedupes(manifest, corpus_cfg, pipeline_cfg):
    sel = select_docs(
        manifest,
        corpus_cfg,
        pipeline_cfg,
        docs=" bbb-0001--style-a,aaa-0001--style-a,bbb-0001--style-a,",
    )
    assert sel.how == "docs"
    assert sel.doc_ids == ("bbb-0001--style-a", "aaa-0001--style-a")


def test_docs_file_with_comments(tmp_path, manifest, corpus_cfg, pipeline_cfg):
    f = tmp_path / "docs.txt"
    f.write_text("# 対象\naaa-0001--style-b  # 1 件目\n\nbbb-0001--style-a\n", encoding="utf-8")
    assert read_docs_file(f) == ["aaa-0001--style-b", "bbb-0001--style-a"]
    sel = select_docs(manifest, corpus_cfg, pipeline_cfg, docs_file=f)
    assert sel.how == "docs_file"
    assert len(sel.doc_ids) == 2


def test_missing_docs_file(tmp_path, manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="無い"):
        select_docs(manifest, corpus_cfg, pipeline_cfg, docs_file=tmp_path / "none.txt")


def test_more_than_one_way_is_an_error(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="1 つだけ"):
        select_docs(
            manifest, corpus_cfg, pipeline_cfg, docs="aaa-0001--style-a", slice_name="pilot"
        )


def test_unknown_and_not_ready_docs_stop(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError) as e:
        select_docs(manifest, corpus_cfg, pipeline_cfg, docs="zzz,ccc-0001--style-a")
    assert "manifest に無い: zzz" in str(e.value)
    assert "ready でない: ccc-0001--style-a（failed）" in str(e.value)


def test_unknown_slice_lists_choices(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="選べるもの"):
        select_docs(manifest, corpus_cfg, pipeline_cfg, slice_name="nope")


def test_empty_docs_arg(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="0 件"):
        select_docs(manifest, corpus_cfg, pipeline_cfg, docs=" , ")


def test_estimate_uses_unit_prices(corpus_cfg, pipeline_cfg):
    # 10 ページ × 0.01 + 図 3 × 領域比 2.0 × 0.1
    assert estimate_credits(10, 3, pipeline_cfg, corpus_cfg) == pytest.approx(0.1 + 0.6)


def test_empty_docs_does_not_fall_back_to_default_slice(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="0 件"):
        select_docs(manifest, corpus_cfg, pipeline_cfg, docs="")


def test_empty_slice_name_is_an_error_not_the_default(manifest, corpus_cfg, pipeline_cfg):
    with pytest.raises(SelectionError, match="スライス ''"):
        select_docs(manifest, corpus_cfg, pipeline_cfg, slice_name="")

"""ローカル実行：架空の条文から作った PDF を、移植した読み取りの全経路に通す。

実データを使わないので、データセットの無い環境でも走る。期待値は移植した規則の振る舞い
（条項木・引用・参照・体裁の判定・当事者）であり、この PDF のために規則を変えていない。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fixtures.configs import make_corpus_cfg, make_pipeline_cfg
from fixtures.synthetic_dataset import SyntheticDoc, build_dataset
from fixtures.synthetic_pdf import CONTRACT_PAGES, YAKKAN_PAGES, build_pdf

from jpdocread.fetch.sources import LocalSource
from jpdocread.local import RunDirs, local_read, predict_view, read_options
from jpdocread.worker import run_worker

YDOC = "synth-0001--syn-a4-1col"
CDOC = "synthc-0001--ct-a4-1col"


def _opts(builder: str) -> dict:
    return {
        "structure_builder": builder,
        "parties": True,
        "defined_terms": True,
        "known_limits": {"source": "test"},
    }


@pytest.fixture(scope="module")
def synth_out(tmp_path_factory) -> dict[str, dict]:
    """両方の合成 PDF を作業プロセスで読み、出力 JSON を返す（1 回だけ走らせる）。"""
    root = tmp_path_factory.mktemp("synth")
    docs = root / "docs"
    build_pdf(docs / YDOC / "doc.pdf", YAKKAN_PAGES)
    build_pdf(docs / CDOC / "doc.pdf", CONTRACT_PAGES)
    out = {}
    for doc, builder in ((YDOC, "yakkan"), (CDOC, "contract")):
        r = run_worker(
            "read",
            {"doc_ids": [doc], "options": _opts(builder), "layout_from": None},
            docs=docs,
            work=root / f"work-{builder}",
            out=root / f"out-{builder}",
        )
        assert r == {"done": [doc], "errors": {}}
        out[builder] = json.loads(
            (root / f"out-{builder}" / f"{doc}.json").read_text(encoding="utf-8")
        )
    return out


def test_synthetic_pdf_has_a_japanese_text_layer(tmp_path):
    import pdfplumber

    p = build_pdf(tmp_path / "doc.pdf", YAKKAN_PAGES)
    with pdfplumber.open(p) as pdf:
        assert len(pdf.pages) == 2
        lines = pdf.pages[1].extract_text().splitlines()
    assert lines[0].replace(" ", "　") == "第１章　総則"  # 全角空白は抽出で半角になる
    assert lines[1] == "第１条（この約款の目的）"


def test_yakkan_tree_cites_chapter_article_item(synth_out):
    o = synth_out["yakkan"]
    cits = [e["citation"] for e in o["outline"]]
    assert "第1章 第2条 （１）" in cits and "第2章 第4条 （２）" in cits
    assert cits.index("第1章") < cits.index("第1章 第1条") < cits.index("第2章")
    # 表紙（1 ページ目）は構造の入力から外れる
    assert all(e.get("page", 2) >= 2 for e in o["elements"])


def test_yakkan_reference_is_resolved_to_citation(synth_out):
    """本文の「第２条に定める」が引用パスに解決される（参照の規則）。"""
    assert ("第2章 第3条", "第1章 第2条") in {
        (r["from_citation"], r["to_citation"]) for r in synth_out["yakkan"]["refs"]
    }


def test_yakkan_output_has_empty_contract_keys(synth_out):
    o = synth_out["yakkan"]
    assert (o["numbering_scheme"], o["parties"], o["defined_terms_detail"]) == (None, [], [])


def test_contract_scheme_and_parties(synth_out):
    o = synth_out["contract"]
    assert o["numbering_scheme"] == "contract-standard"
    assert {(p["alias"], p["name"]) for p in o["parties"]} == {
        ("甲", "株式会社アカシ"),
        ("乙", "株式会社イズミ"),
    }
    assert "第２条 ２" in [e["citation"] for e in o["outline"]]  # 契約書の引用は字形を変えない


def test_both_corpora_emit_the_same_top_level_keys(synth_out):
    assert set(synth_out["yakkan"]) == set(synth_out["contract"])


def test_text_is_not_normalized(synth_out):
    """字形を正規化して保存しない。全角の数字・括弧が逐語で残る。"""
    assert "第１条" in [e["citation"] for e in synth_out["contract"]["outline"]]
    assert "第1章 第2条 （１）" in [e["citation"] for e in synth_out["yakkan"]["outline"]]


def test_no_ai_and_no_layout_is_recorded(synth_out):
    for o in synth_out.values():
        assert o["provenance"]["local"] == {"layout": "none", "ai_called": False}


def test_worker_records_per_doc_failure_without_stopping(tmp_path):
    """1 文書の失敗は errors に残し、他の文書は続ける（黙って捨てない）。"""
    docs = tmp_path / "docs"
    build_pdf(docs / YDOC / "doc.pdf", YAKKAN_PAGES)
    r = run_worker(
        "read",
        {"doc_ids": ["missing-0001--syn", YDOC], "options": _opts("auto"), "layout_from": None},
        docs=docs,
        work=tmp_path / "w",
        out=tmp_path / "o",
    )
    assert r["done"] == [YDOC]
    assert list(r["errors"]) == ["missing-0001--syn"]


def test_worker_contract_builder_on_yakkan_pdf_fails_explicitly(tmp_path):
    docs = tmp_path / "docs"
    build_pdf(docs / YDOC / "doc.pdf", YAKKAN_PAGES)
    r = run_worker(
        "read",
        {"doc_ids": [YDOC], "options": _opts("contract"), "layout_from": None},
        docs=docs,
        work=tmp_path / "w",
        out=tmp_path / "o",
    )
    assert r["done"] == [] and "契約書の体裁" in r["errors"][YDOC]


def test_layout_from_seeds_tables_from_the_given_markdown(tmp_path, synth_out):
    """--layout-from：別 run の出力の text_with_furniture を S20 のキャッシュとして使い、表を組み直す。"""
    docs = tmp_path / "docs"
    build_pdf(docs / YDOC / "doc.pdf", YAKKAN_PAGES)
    prev = tmp_path / "prev"
    prev.mkdir()
    md = "| 区分 | 金額 |\n| --- | --- |\n| 見本 | 100 |"
    run = {
        "pages": [
            {"number": 1, "text_with_furniture": ""},
            {"number": 2, "text_with_furniture": md},
        ]
    }
    (prev / f"{YDOC}.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    r = run_worker(
        "read",
        {"doc_ids": [YDOC], "options": _opts("yakkan"), "layout_from": str(prev)},
        docs=docs,
        work=tmp_path / "w",
        out=tmp_path / "o",
    )
    assert r["errors"] == {}
    o = json.loads((tmp_path / "o" / f"{YDOC}.json").read_text(encoding="utf-8"))
    assert o["provenance"]["local"]["layout"] == "from_run"
    assert len(o["tables"]) == 1 and len(synth_out["yakkan"]["tables"]) == 0


def test_predict_view_contains_only_doc_pdf(tmp_path):
    ds = build_dataset(tmp_path / "ds", [SyntheticDoc("bbb-0001--style-a", "bbb-0001")])
    view = predict_view(ds, ["bbb-0001--style-a"], tmp_path / "view")
    assert sorted(p.name for p in view.rglob("*") if p.is_file() or p.is_symlink()) == ["doc.pdf"]
    assert not (view / "manifest.json").exists()


def test_run_dirs_are_under_git_ignored_roots(tmp_path):
    d = RunDirs.for_run("r1", "yakkan", home=tmp_path)
    assert d.out == tmp_path / "out" / "r1" / "yakkan"
    assert d.work == tmp_path / "work" / "r1" / "yakkan"
    assert d.results == tmp_path / "results" / "r1" / "yakkan"


def test_read_options_follow_corpus_config():
    c = make_corpus_cfg(structure_builder="contract", known_limits={"source": "s"})
    assert read_options(c) == {
        "structure_builder": "contract",
        "parties": c.features.parties,
        "defined_terms": c.features.defined_terms,
        "stitch_tables": c.tables.stitch,
        "supersede_empty_upper": c.structure.supersede_empty_upper,
        "filter_figure_regions": c.figures.filter_regions,
        "label_routine_repairs": c.structure.label_routine_repairs,
        "known_limits": {"source": "s"},
    }


def test_local_read_end_to_end_with_fetch_and_compare(tmp_path):
    """取得（照合）→ 予測用の入力 → 読み取り → 自分自身との照合（一致）。"""
    ds = build_dataset(
        tmp_path / "src", [SyntheticDoc(YDOC, "synth-0001", pages=2, pdf_pages=YAKKAN_PAGES)]
    )
    corpus = make_corpus_cfg(
        figure_shots=[], eval_excluded=[], slices={"pilot": [YDOC]}, known_limits={"source": "test"}
    )
    common = {
        "data_dir": tmp_path / "data",
        "home": tmp_path,
        "docs": None,
        "docs_file": None,
        "slice_name": "pilot",
    }
    first = local_read(LocalSource(ds), corpus, make_pipeline_cfg(), run_id="a", **common)
    assert first["done"] == [YDOC] and first["errors"] == {}
    assert Path(first["out_dir"]) == tmp_path / "out" / "a" / corpus.name
    second = local_read(
        LocalSource(ds),
        corpus,
        make_pipeline_cfg(),
        run_id="b",
        compare_with=Path(first["out_dir"]),
        **common,
    )
    assert second["compare"]["mismatches"] == {}


def test_local_eval_passes_exclusions_and_slices_and_records(tmp_path, monkeypatch):
    """採点の配線：正解込みで取得し、評価除外とスライス（部分集合）を採点に渡し、results/ に記録する。

    採点そのもの（eval/）は tests/ported の移植したテストと、実データでの照合で検査する。
    """
    import jpdocread.local as local

    seen = {}

    def fake_worker(task, args, *, docs, work, out):
        seen.update(task=task, args=args, docs=docs)
        summary = {"n_docs": 1, "citation": {"citation_error_rate": 0.0}, "structure": {}}
        return {"result": {"summary": summary, "docs": [], "integrity": {"ok": True}}}

    monkeypatch.setattr(local, "run_worker", fake_worker)
    ds = build_dataset(
        tmp_path / "src",
        [
            SyntheticDoc("aaa-0001--style-a", "aaa-0001"),
            SyntheticDoc("bbb-0001--style-a", "bbb-0001"),
        ],
    )
    corpus = make_corpus_cfg(slices={"two": ["aaa-0001--style-a", "bbb-0001--style-a"]})
    rec = local.local_eval(
        LocalSource(ds),
        corpus,
        make_pipeline_cfg(),
        run_id="e1",
        pred_dir=tmp_path / "pred",
        data_dir=tmp_path / "data",
        home=tmp_path,
        docs=None,
        docs_file=None,
        slice_name="two",
    )
    assert seen["task"] == "eval"
    assert seen["args"]["eval_excluded"] == list(corpus.eval_excluded)
    assert seen["args"]["subsets"] == corpus.slices
    assert (seen["docs"] / "bbb-0001--style-a" / "answer.json").exists()  # 採点側は正解を持つ
    assert rec["eval_excluded"] == ["aaa-0001--style-a"]
    saved = json.loads(
        (tmp_path / "results" / "e1" / corpus.name / "eval.json").read_text(encoding="utf-8")
    )
    assert saved["summary"]["n_docs"] == 1 and saved["run_id"] == "e1"


def test_output_records_read_options(synth_out):
    """空の parties 等が「対象外」か「抽出して 0 件」かを provenance で区別できる。"""
    y = synth_out["yakkan"]["provenance"]["read_options"]
    c = synth_out["contract"]["provenance"]["read_options"]
    assert y == {
        "structure_builder": "yakkan",
        "parties": True,
        "defined_terms": True,
        "contract_scheme_detected": False,
    }
    assert c["contract_scheme_detected"] is True


def test_build_output_requires_known_limits():
    from jpdocread.read.integrate import ReadOptions, build_output

    with pytest.raises(ValueError, match="known_limits"):
        build_output("x", ReadOptions())


def test_layout_from_without_text_with_furniture_is_an_error(tmp_path):
    docs = tmp_path / "docs"
    build_pdf(docs / YDOC / "doc.pdf", YAKKAN_PAGES)
    prev = tmp_path / "prev"
    prev.mkdir()
    run = {"pages": [{"number": 1}, {"number": 2, "text_with_furniture": ""}]}
    (prev / f"{YDOC}.json").write_text(json.dumps(run), encoding="utf-8")
    r = run_worker(
        "read",
        {"doc_ids": [YDOC], "options": _opts("yakkan"), "layout_from": str(prev)},
        docs=docs,
        work=tmp_path / "w",
        out=tmp_path / "o",
    )
    assert r["done"] == [] and "text_with_furniture が無いページ: [1]" in r["errors"][YDOC]


def test_contract_compare_does_not_ignore_missing_contract_keys(tmp_path):
    """契約書の照合では、比較先に parties 等が無ければ不一致（約款だけが追加キーの欠落を許す）。"""
    ds = build_dataset(
        tmp_path / "src", [SyntheticDoc(CDOC, "synthc-0001", pages=2, pdf_pages=CONTRACT_PAGES)]
    )
    common = {"data_dir": tmp_path / "data", "home": tmp_path, "docs": None, "docs_file": None}
    results = {}
    for builder in ("contract", "yakkan"):
        corpus = make_corpus_cfg(
            name=f"c{builder}",
            structure_builder=builder,
            figure_shots=[],
            eval_excluded=[],
            slices={"pilot": [CDOC]},
            known_limits={"source": "test"},
        )
        pc = make_pipeline_cfg()
        first = local_read(
            LocalSource(ds), corpus, pc, run_id=f"a{builder}", slice_name="pilot", **common
        )
        legacy = tmp_path / f"legacy-{builder}"
        legacy.mkdir()
        out = Path(first["out_dir"]) / f"{CDOC}.json"
        if not out.exists():  # builder=yakkan でも契約書 PDF は読める（約款の組み立て器で組む）
            raise AssertionError(first["errors"])
        o = json.loads(out.read_text(encoding="utf-8"))
        o.pop("parties")
        (legacy / f"{CDOC}.json").write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
        second = local_read(
            LocalSource(ds),
            corpus,
            pc,
            run_id=f"b{builder}",
            compare_with=legacy,
            slice_name="pilot",
            **common,
        )
        results[builder] = second["compare"]["mismatches"]
    assert results["contract"] == {CDOC: ["parties"]}
    assert results["yakkan"] == {}


def test_cli_eval_fails_when_predictions_are_missing(monkeypatch, capsys):
    import jpdocread.local as local
    from jpdocread import cli

    summary = {
        "n_docs": 1,
        "missing_predictions": ["d2"],
        "citation": {"citation_error_rate": 0.0, "n_wrong": 0, "n_elements": 1},
        "structure": {"article": {"recall": 1.0, "precision": 1.0}},
    }
    rec = {"corpus": "contract", "run_id": "r", "eval_excluded": [], "summary": summary}
    monkeypatch.setattr(local, "local_eval", lambda *a, **k: rec)
    monkeypatch.setattr(cli, "make_source", lambda c: None)
    assert cli.main(["eval", "--corpus", "contract", "--pred", "x", "--run-id", "r"]) == 1
    assert "予測が無い文書 1 件" in capsys.readouterr().err

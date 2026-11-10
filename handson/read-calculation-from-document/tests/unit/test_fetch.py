"""取得・adapter・照合・分割・対象選択（合成データセットと偽の Hub で試す）。"""

from __future__ import annotations

import json

import pytest
from fixtures.fake_hub import FakeHub
from fixtures.synthetic_dataset import (
    CONTRACT_DOCS,
    GOLD_COLUMNS,
    YAKKAN_DOCS,
    build_contract,
    build_yakkan,
)

from jpcalc.config import load_corpus_config, load_guard_config
from jpcalc.eval.catalog import build_public_index, write_public_index
from jpcalc.eval.gold_fetch import GoldFetchError, check_disjoint, fetch_gold, gold_patterns
from jpcalc.fetch.adapters import (
    PUBLIC_INDEX,
    AdapterError,
    check_predict_paths,
    match_path,
    pdf_refs,
    read_public_index,
)
from jpcalc.fetch.pilot import pick
from jpcalc.fetch.run import FETCH_RECORD, fetch_predict
from jpcalc.fetch.select import SelectError, select
from jpcalc.fetch.sources import HuggingFaceSource, LocalSource, SourceError, source_from_config
from jpcalc.fetch.split import (
    SplitError,
    bases_sha256,
    check_split,
    compute_split,
    summarize,
)
from jpcalc.fetch.verify import VerifyError

REV = "0" * 40


@pytest.fixture
def yakkan(tmp_path):
    cfg = load_corpus_config("yakkan")
    hub = FakeHub(build_yakkan(tmp_path / "hub"))
    src = HuggingFaceSource(cfg.source.huggingface.repo_id, REV, client=hub)
    return cfg, hub, src, tmp_path / "data"


@pytest.fixture
def contract(tmp_path):
    cfg = load_corpus_config("contract")
    root, lfs = build_contract(tmp_path / "hub")
    hub = FakeHub(root, lfs)
    src = HuggingFaceSource(cfg.source.huggingface.repo_id, REV, client=hub)
    return cfg, hub, src, tmp_path / "data"


def _index(cfg, src, data):
    rows = build_public_index(cfg, src)
    write_public_index(rows, data)
    return read_public_index(data / PUBLIC_INDEX)


# ---- 取得元 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("rev", ["main", "v1", "f6d368a", "F" * 40, "g" * 40])
def test_hf_source_rejects_unpinned_revision(rev):
    with pytest.raises(SourceError, match="40 桁"):
        HuggingFaceSource("x/y", rev, client=FakeHub(None))


@pytest.mark.parametrize("bad", ["/etc/passwd", "../x.pdf", ""])
def test_source_rejects_escaping_paths(yakkan, bad):
    _, _, src, _ = yakkan
    with pytest.raises(SourceError, match="相対パス"):
        src.read_bytes(bad)


def test_local_source(tmp_path):
    root = build_yakkan(tmp_path / "copy")
    src = LocalSource(root)
    assert src.lfs_sha256(["x"]) == {}
    got = src.fetch_files(tmp_path / "out", ["documents/auto-0001-c1/auto-0001-c1--s-a/doc.pdf"])
    assert got[0].is_file()
    with pytest.raises(SourceError):
        LocalSource(tmp_path / "missing")


def test_source_from_config_local_needs_setting(tmp_path):
    cfg = load_corpus_config("yakkan").model_copy(deep=True)
    object.__setattr__(cfg.source, "kind", "local")
    with pytest.raises(SourceError, match="未設定"):
        source_from_config(cfg, env={})
    build_yakkan(tmp_path / "copy")
    s = source_from_config(cfg, env={"DATA_ROOT_YAKKAN": str(tmp_path / "copy")})
    assert isinstance(s, LocalSource)


# ---- 公開索引（評価側が作り、予測側が読む） ---------------------------------------------------


@pytest.mark.parametrize("fixture", ["yakkan", "contract"])
def test_public_index_has_no_gold_columns(request, fixture):
    cfg, hub, src, data = request.getfixturevalue(fixture)
    rows = _index(cfg, src, data)
    text = (data / PUBLIC_INDEX).read_text(encoding="utf-8")
    for col in (*GOLD_COLUMNS, "n_rules", "challenge_type", "totals", "files"):
        assert f'"{col}"' not in text
    assert all(p["sha256"] for r in rows for p in r["pdfs"])
    # 完全な索引はメモリ上で読むだけで、ディスクには残さない
    assert hub.gets == [cfg.index.file]
    assert not list(data.rglob(cfg.index.file.split("/")[-1]))


def test_public_index_rejects_extra_columns(yakkan, tmp_path):
    cfg, _, src, data = yakkan
    rows = build_public_index(cfg, src)
    rows[0]["rules"] = 5
    write_public_index(rows, data)
    with pytest.raises(AdapterError, match="許されない列"):
        read_public_index(data / PUBLIC_INDEX)


def test_adapter_yakkan(yakkan):
    cfg, _, src, data = yakkan
    refs = pdf_refs(_index(cfg, src, data), cfg)
    assert len(refs) == sum(len(s) for *_, s in YAKKAN_DOCS)
    r = next(x for x in refs if x.pdf_id == "auto-0001-c1--s-b")
    assert r.hub_path == "documents/auto-0001-c1/auto-0001-c1--s-b/doc.pdf"
    assert (r.split_group, r.stratum, r.style) == ("auto-0001", "auto", "s-b")


def test_adapter_contract(contract):
    cfg, _, src, data = contract
    refs = pdf_refs(_index(cfg, src, data), cfg)
    assert len(refs) == len(CONTRACT_DOCS)
    r = next(x for x in refs if x.doc_id == "con-0102")
    assert (r.pdf_id, r.hub_path) == ("con-0102--ct-y", "inputs/con-0102/con-0102--ct-y.pdf")
    assert r.split_group == "con-0001"


def test_adapter_rejects_path_not_matching_template(yakkan):
    cfg, _, src, data = yakkan
    rows = _index(cfg, src, data)
    rows[0]["pdfs"][0]["hub_path"] = "documents/x/policy.json"
    with pytest.raises(AdapterError, match="ひな型"):
        pdf_refs(rows, cfg)


# ---- 予測用・評価用の allow-list --------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("documents/a/a--s/doc.pdf", True),
        ("documents/a/policy.json", False),
        ("documents/a/a--s/layout.json", False),
        ("documents/a/calc/x.pdf", False),  # `*` は / をまたがない
        ("inputs/c/c--s.pdf", True),
        ("inputs/c/contract.json", False),
        ("answers/c/c--s.pdf", False),
    ],
)
def test_predict_allow_list(path, ok):
    allow = [p for v in load_guard_config().predict_allow.values() for p in v]
    if ok:
        check_predict_paths([path], allow)
    else:
        with pytest.raises(AdapterError):
            check_predict_paths([path], allow)


def test_match_path_segments():
    assert match_path("a/b/c.pdf", "a/*/c.pdf")
    assert not match_path("a/b/x/c.pdf", "a/*/c.pdf")


@pytest.mark.parametrize("name", ["yakkan", "contract"])
def test_gold_patterns_are_disjoint_from_predict(name):
    cfg = load_corpus_config(name)
    pats = gold_patterns(cfg, ["d1"])
    check_disjoint(pats, load_guard_config().predict_allow[name])
    assert cfg.index.file not in pats
    with pytest.raises(GoldFetchError):
        check_disjoint([*pats, cfg.paths.pdf.format(doc_id="d1", style="s")], [])


def test_gold_fetch_goes_to_separate_place(yakkan, tmp_path):
    cfg, _, src, _ = yakkan
    got = fetch_gold(
        cfg, src, ["auto-0001-c1"], tmp_path / "eval", load_guard_config().predict_allow["yakkan"]
    )
    rels = {str(p.relative_to(tmp_path / "eval")) for p in got}
    assert "documents/auto-0001-c1/policy.json" in rels
    assert "documents/auto-0001-c1/calc/spec.json" in rels
    assert not any(r.endswith(".pdf") for r in rels)
    assert "index.json" not in rels


# ---- 取得と照合 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["yakkan", "contract"])
def test_fetch_predict_takes_only_pdfs(request, fixture):
    cfg, hub, src, data = request.getfixturevalue(fixture)
    refs = pdf_refs(_index(cfg, src, data), cfg)
    allow = load_guard_config().predict_allow[cfg.name]
    rep, rec = fetch_predict(refs, src, data, allow)
    assert len(rep.verified) == len(refs) and not rep.unverified
    assert all(p.endswith(".pdf") for pats in hub.snapshots for p in pats)
    files = {str(p.relative_to(data)) for p in data.rglob("*") if p.is_file()}
    assert files - {PUBLIC_INDEX, FETCH_RECORD} == {f"files/{r.hub_path}" for r in refs}
    assert all(p["page_count"] >= 1 for p in rec["pdfs"])
    # 2 回目は取り直さない（照合だけ）。記録は PDF ID ごとに残る
    _, rec2 = fetch_predict(refs[:1], src, data, allow)
    assert rec2["n_downloaded"] == 0
    assert json.loads((data / FETCH_RECORD).read_text())["n_pdfs"] == len(refs)


def test_tampered_file_stops(yakkan):
    cfg, _, src, data = yakkan
    refs = pdf_refs(_index(cfg, src, data), cfg)[:1]
    allow = load_guard_config().predict_allow["yakkan"]
    fetch_predict(refs, src, data, allow)
    f = data / "files" / refs[0].hub_path
    f.write_bytes(f.read_bytes() + b"x")
    # 取得済みでも照合が通らなければ取り直す（取り直して一致すれば通る）
    fetch_predict(refs, src, data, allow)
    # 取得元のファイル自体が改ざんされていれば止まる
    hub_file = src.client.root / refs[0].hub_path
    hub_file.write_bytes(hub_file.read_bytes() + b"x")
    f.write_bytes(b"broken")
    with pytest.raises(VerifyError, match="一致しない"):
        fetch_predict(refs, src, data, allow)


def test_missing_checksum_is_unverified(contract):
    cfg, hub, src, data = contract
    hub.lfs = {}
    refs = pdf_refs(_index(cfg, src, data), cfg)
    rep, _ = fetch_predict(refs, src, data, load_guard_config().predict_allow["contract"])
    assert rep.verified == [] and len(rep.unverified) == len(refs)


def test_fetch_refuses_gold_path(yakkan):
    from dataclasses import replace

    cfg, _, src, data = yakkan
    refs = pdf_refs(_index(cfg, src, data), cfg)
    bad = [replace(refs[0], hub_path="documents/auto-0001-c1/policy.json")]
    with pytest.raises(AdapterError, match="allow-list"):
        fetch_predict(bad, src, data, load_guard_config().predict_allow["yakkan"])


# ---- 分割 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["yakkan", "contract"])
def test_split_is_base_level_and_disjoint(request, fixture):
    cfg, _, src, data = request.getfixturevalue(fixture)
    rows = _index(cfg, src, data)
    sp = compute_split(rows, salt=cfg.split.salt, dev_fraction=cfg.split.dev_fraction)
    assert not set(sp["dev"]) & set(sp["holdout"])
    assert set(sp["dev"]) | set(sp["holdout"]) == {r["split_group"] for r in rows}
    # 層ごとに round(base 数 × 0.4) 件が DEV
    by = {}
    for r in rows:
        by.setdefault(r["stratum"], set()).add(r["split_group"])
    assert len(sp["dev"]) == sum(round(len(b) * cfg.split.dev_fraction) for b in by.values())
    # 決定的：もう一度計算しても同じ
    assert sp == compute_split(rows, salt=cfg.split.salt, dev_fraction=cfg.split.dev_fraction)


def test_split_check(yakkan):
    cfg, _, src, data = yakkan
    rows = _index(cfg, src, data)
    kw = dict(revision=REV, salt=cfg.split.salt, dev_fraction=0.4)
    entry = summarize(rows, compute_split(rows, salt=cfg.split.salt, dev_fraction=0.4), **kw)
    check_split("yakkan", entry, {"yakkan": entry})
    other = summarize(
        rows, compute_split(rows, salt="other:", dev_fraction=0.4), **{**kw, "salt": "other:"}
    )
    with pytest.raises(SplitError):
        check_split("yakkan", entry, {"yakkan": other})
    with pytest.raises(SplitError, match="記録が無い"):
        check_split("yakkan", entry, {})


def test_split_rejects_base_in_two_strata():
    rows = [{"split_group": "b", "stratum": "x"}, {"split_group": "b", "stratum": "y"}]
    with pytest.raises(SplitError, match="複数の層"):
        compute_split(rows, salt="s", dev_fraction=0.4)


def test_bases_sha256_definition():
    import hashlib

    assert bases_sha256(["b", "a"]) == hashlib.sha256(b"a\nb").hexdigest()


def test_repo_split_yaml_matches_recorded_hashes():
    # 分割の照合値（設計時に公開列だけから計算した値）と、記録した configs/split.yaml が一致すること
    from jpcalc.fetch.split import load_split

    sp = load_split()
    assert sp["yakkan"]["dev"]["sha256"].startswith("aaf18140805d")
    assert sp["yakkan"]["holdout"]["sha256"].startswith("eb08f4b2ed85")
    assert sp["contract"]["dev"]["sha256"].startswith("1a6619f6f1f0")
    assert sp["contract"]["holdout"]["sha256"].startswith("b53d9d86ed04")
    for c in ("yakkan", "contract"):
        assert not set(sp[c]["dev"]["bases"]) & set(sp[c]["holdout"]["bases"])
        for side in ("dev", "holdout"):
            assert bases_sha256(sp[c][side]["bases"]) == sp[c][side]["sha256"]


# ---- 対象の選択 ---------------------------------------------------------------------------------


@pytest.fixture
def chosen(yakkan):
    cfg, _, src, data = yakkan
    rows = _index(cfg, src, data)
    refs = pdf_refs(rows, cfg)
    sp = summarize(
        rows,
        compute_split(rows, salt=cfg.split.salt, dev_fraction=0.4),
        revision=REV,
        salt=cfg.split.salt,
        dev_fraction=0.4,
    )
    return refs, sp


def test_select_exactly_one(chosen):
    refs, sp = chosen
    with pytest.raises(SelectError, match="1 つだけ"):
        select(refs, sp)
    with pytest.raises(SelectError, match="1 つだけ"):
        select(refs, sp, docs="a", slice_name="dev")


def test_select_doc_expands_styles(chosen):
    refs, sp = chosen
    dev_doc = next(r for r in refs if r.split_group in sp["dev"]["bases"])
    picked = select(refs, sp, docs=dev_doc.doc_id)
    assert {r.doc_id for r in picked} == {dev_doc.doc_id}
    assert len(picked) == sum(1 for r in refs if r.doc_id == dev_doc.doc_id)


def test_select_unknown_id(chosen):
    refs, sp = chosen
    with pytest.raises(SelectError, match="未知の ID"):
        select(refs, sp, docs="nope-0001")


def test_holdout_needs_explicit_flag(chosen):
    refs, sp = chosen
    ho = next(r for r in refs if r.split_group in sp["holdout"]["bases"])
    with pytest.raises(SelectError, match="HOLDOUT"):
        select(refs, sp, docs=ho.pdf_id)
    with pytest.raises(SelectError, match="HOLDOUT"):
        select(refs, sp, slice_name="holdout")
    assert select(refs, sp, slice_name="holdout", allow_holdout=True)


def test_slice_lists_must_be_dev(chosen, tmp_path):
    refs, sp = chosen
    ho = next(r for r in refs if r.split_group in sp["holdout"]["bases"])
    with pytest.raises(SelectError, match="DEV でない"):
        select(refs, sp, slice_name="pilot", slice_lists={"pilot": [ho.pdf_id]}, allow_holdout=True)
    with pytest.raises(SelectError, match="空"):
        select(refs, sp, slice_name="pilot", slice_lists={})
    f = tmp_path / "ids.txt"
    dev = next(r for r in refs if r.split_group in sp["dev"]["bases"])
    f.write_text(f"# コメント\n{dev.pdf_id}\n\n", encoding="utf-8")
    assert [r.pdf_id for r in select(refs, sp, docs_file=f)] == [dev.pdf_id]


# ---- pilot の選定 ------------------------------------------------------------------------------


def test_pick_pilot_is_dev_only_and_disjoint_from_shots(chosen):
    refs, sp = chosen
    dev = [r for r in refs if r.split_group in sp["dev"]["bases"]]
    pilot, shots = pick(dev, n_pilot=2, n_shots=2)
    by = {r.pdf_id: r for r in refs}
    assert set(pilot) <= {r.pdf_id for r in dev}
    assert not {by[p].split_group for p in pilot} & {by[s].split_group for s in shots}
    assert len({by[p].split_group for p in pilot}) == len(pilot)
    assert (pilot, shots) == pick(dev, n_pilot=2, n_shots=2)


def test_slices_must_not_share_bases(chosen):
    from jpcalc.fetch.select import check_slices_disjoint

    refs, sp = chosen
    dev = [r for r in refs if r.split_group in sp["dev"]["bases"]]
    a, b = dev[0], next(r for r in dev if r.split_group == dev[0].split_group)
    with pytest.raises(SelectError, match="base を共有"):
        check_slices_disjoint(refs, {"pilot": [a.pdf_id], "shots": [b.pdf_id]})
    with pytest.raises(SelectError, match="base を共有"):
        select(refs, sp, slice_name="pilot", slice_lists={"pilot": [a.pdf_id], "shots": [b.doc_id]})


def test_repo_slices_are_dev_and_disjoint():
    # configs/pipeline.yaml の pilot・shots が DEV にあり、両者が base を共有しないこと（両コーパス）。
    # 公開索引（data/）が無い環境では、configs/split.yaml の base 一覧と ID の形から確かめる
    from jpcalc.config import load_pipeline_config
    from jpcalc.fetch.split import load_split

    sp = load_split()
    for name, sl in load_pipeline_config().slices.items():
        assert sl.pilot and sl.shots
        dev = set(sp[name]["dev"]["bases"])
        docs = sp[name]
        # pdf_id = <doc_id>--<style>。base は DEV/HOLDOUT のどちらかの一覧に必ずある
        allb = set(docs["dev"]["bases"]) | set(docs["holdout"]["bases"])

        def base_of(pid, allb=allb):
            doc = pid.split("--")[0]
            hits = [b for b in allb if doc == b or doc.startswith(b + "-")]
            assert len(hits) == 1, (pid, hits)
            return hits[0]

        if name == "contract":  # 契約書の文書 ID は base と形が違うので、公開索引で引く
            from jpcalc.common.paths import corpus_dir
            from jpcalc.config import load_corpus_config
            from jpcalc.fetch.adapters import PUBLIC_INDEX, read_public_index

            cfg = load_corpus_config(name)
            path = corpus_dir(name, cfg.source.huggingface.revision) / PUBLIC_INDEX
            if not path.is_file():
                pytest.skip(
                    "契約書の公開索引が無い（`jpcalc index --corpus contract` の後に確かめる）"
                )
            m = {r["doc_id"]: r["split_group"] for r in read_public_index(path)}
            base_of = lambda pid, m=m: m[pid.split("--")[0]]  # noqa: E731
        pb, sb = {base_of(p) for p in sl.pilot}, {base_of(s) for s in sl.shots}
        assert pb <= dev and sb <= dev and not pb & sb, name


def test_fetch_leaves_no_hub_metadata(yakkan):
    # 取得元が置き場所に書く管理用のファイル（リポジトリ全体の一覧）を、予測用の置き場所に残さない
    cfg, _, src, data = yakkan
    refs = pdf_refs(_index(cfg, src, data), cfg)
    fetch_predict(refs, src, data, load_guard_config().predict_allow["yakkan"])
    from jpcalc.fetch.sources import all_files_under

    left = [p.relative_to(data / "files").as_posix() for p in all_files_under(data / "files")]
    assert left and all(p.endswith("/doc.pdf") for p in left)


@pytest.mark.parametrize(
    "extra", [".cache/huggingface/trees/x.json", "documents/a/policy.json", "notes.txt"]
)
def test_fetch_stops_on_foreign_file_in_predict_dir(yakkan, extra):
    from jpcalc.fetch.run import check_files_dir

    cfg, _, src, data = yakkan
    refs = pdf_refs(_index(cfg, src, data), cfg)
    allow = load_guard_config().predict_allow["yakkan"]
    fetch_predict(refs[:1], src, data, allow)
    f = data / "files" / extra
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    with pytest.raises(AdapterError, match="PDF 以外"):
        check_files_dir(data / "files", allow)
    with pytest.raises(AdapterError, match="PDF 以外"):
        fetch_predict(refs[:1], src, data, allow)


def test_eval_dir_is_outside_predict_dir(tmp_path):
    from jpcalc.common.paths import eval_corpus_dir

    ok = eval_corpus_dir("yakkan", REV, eval_dir=tmp_path / "eval", data_dir=tmp_path / "data")
    assert ok == (tmp_path / "eval" / "yakkan" / REV).resolve()
    for bad in (tmp_path / "data", tmp_path / "data" / "eval", tmp_path):
        with pytest.raises(ValueError, match="重なって"):
            eval_corpus_dir("yakkan", REV, eval_dir=bad, data_dir=tmp_path / "data")


@pytest.mark.parametrize("bad", ["a[1]", "x?y", "a*b", "-x", "日本"])
def test_ids_with_wildcards_are_rejected(yakkan, bad):
    cfg, _, src, data = yakkan
    rows = _index(cfg, src, data)
    rows[0]["doc_id"] = bad
    with pytest.raises(AdapterError, match="使えない文字"):
        pdf_refs(rows, cfg)


def test_gold_fetch_rejects_pdf_in_result(yakkan, tmp_path):
    cfg, _, src, _ = yakkan

    class Leaky:
        label = "leaky"

        def fetch_patterns(self, dest, patterns):
            f = dest / "x.pdf"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"%PDF")
            return [f]

    with pytest.raises(GoldFetchError, match="PDF が混ざった"):
        fetch_gold(cfg, Leaky(), ["auto-0001-c1"], tmp_path / "e", [])


def test_dev_slice_excludes_documents_sharing_a_base_with_shots(chosen):
    """dev から、手本（shots）と同じ base の PDF を除く（手本は shots の正解から作るので）。"""
    refs, sp = chosen
    dev = [r for r in refs if r.split_group in sp["dev"]["bases"]]
    shot = dev[0]
    lists = {"pilot": [], "shots": [shot.pdf_id]}
    picked = select(refs, sp, slice_name="dev", slice_lists=lists)
    assert all(r.split_group != shot.split_group for r in picked)
    assert {r.pdf_id for r in picked} == {
        r.pdf_id for r in dev if r.split_group != shot.split_group
    }
    # shots の slice そのもの（make-shots が使う）は変わらない
    assert [r.pdf_id for r in select(refs, sp, slice_name="shots", slice_lists=lists)] == [
        shot.pdf_id
    ]


def test_shot_overlap_finds_explicit_targets(chosen):
    from jpcalc.fetch.select import shot_overlap

    refs, sp = chosen
    dev = [r for r in refs if r.split_group in sp["dev"]["bases"]]
    shot = dev[0]
    same = [r.pdf_id for r in dev if r.split_group == shot.split_group]
    other = next(r.pdf_id for r in dev if r.split_group != shot.split_group)
    assert shot_overlap(refs, [*same, other], [shot.pdf_id]) == same
    assert shot_overlap(refs, [other], [shot.pdf_id]) == []
    assert shot_overlap(refs, same, []) == []

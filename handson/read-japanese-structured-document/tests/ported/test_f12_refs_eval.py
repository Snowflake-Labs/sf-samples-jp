"""F12：S60 の参照関係の採点と guard の `pages/` 検出。"""

from jpdocread.common.guard import GuardResult, check_no_gold_filenames
from jpdocread.eval import evaluate as ev


def _fake(monkeypatch, refs, elements):
    monkeypatch.setattr(ev, "load_elements", lambda d: elements)
    monkeypatch.setattr(ev, "load_source", lambda d: {"derived": {"refs": refs}})


ELS = [
    {"element_id": "a", "node_kind": "paragraph", "citation": "第1条 （1）"},
    {"element_id": "b", "node_kind": "paragraph", "citation": "第2条 （1）"},
    {"element_id": "c", "node_kind": "cell", "citation": ""},
]


def test_unreachable_gold_is_counted_not_dropped(monkeypatch):
    _fake(
        monkeypatch,
        [
            {"from_id": "a", "to_id": "b"},
            {"from_id": "c", "to_id": "b"},
            {"from_id": "a", "to_id": "a"},
            {"from_id": "x", "to_id": "b"},
        ],
        ELS,
    )
    pairs, un = ev.gold_refs("d")
    assert pairs == {("第1条 （1）", "第2条 （1）")}  # 自己参照は除く
    assert un == {"cell": 1, "missing_element": 1}


def test_scores_use_output_refs_and_sum_before_rates(monkeypatch):
    _fake(monkeypatch, [{"from_id": "a", "to_id": "b"}, {"from_id": "c", "to_id": "b"}], ELS)
    pred = {
        "refs": [
            {"from_citation": "第1条 （1）", "to_citation": "第2条 （1）"},
            {"from_citation": "第2条 （1）", "to_citation": "第1条 （1）"},
        ]
    }
    r = ev.ref_scores("d", pred)
    assert (r["tp"], r["pred"], r["gold_reachable"], r["gold_unreachable"]) == (1, 2, 1, 1)
    s = ev.summarize_refs([r, r])
    assert s["recall_reachable"] == 1.0 and s["precision"] == 0.5 and s["recall_all"] == 0.5
    assert s["f1_reachable"] == round(2 * 0.5 / 1.5, 4)


def test_guard_rejects_pages_directory(tmp_path):
    (tmp_path / "m.py").write_text('P = "auto/pages/page-001.png"\n', encoding="utf-8")
    res = GuardResult()
    check_no_gold_filenames(res, tmp_path)
    assert any("pages/" in v for v in res.violations)


def test_empty_citation_pair_is_not_counted(monkeypatch):
    _fake(monkeypatch, [{"from_id": "a", "to_id": "b"}], ELS)
    r = ev.ref_scores("d", {"refs": [{"from_citation": "", "to_citation": "第2条 （1）"}]})
    assert r["pred"] == 0

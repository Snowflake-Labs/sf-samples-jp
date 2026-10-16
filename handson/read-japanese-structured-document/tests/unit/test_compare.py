"""出力 JSON と採点結果の比較（compare.py。移植元との同値確認に使う関数）。逆対照を対で持つ。"""

from __future__ import annotations

import json

import pytest

from jpdocread.compare import EXACT_KEYS, MULTISET_KEYS, compare_dirs, diff_keys, metric_diffs

BASE = {
    "outline": [{"citation": "第1条"}],
    "elements": [{"citation": "第1条", "text": "本文"}],
    "refs": [],
    "tables": [],
    "footnotes": [],
    "enumerations": [],
    "defined_terms": ["見本"],
    "numbering_scheme": None,
    "parties": [],
    "defined_terms_detail": [],
    "term_uses": [{"term": "甲", "in_citation": "第1条"}, {"term": "乙", "in_citation": "第1条"}],
    "pages": [{"number": 1, "text": "AI の出力"}],
}


def test_identical_outputs_match():
    assert diff_keys(BASE, json.loads(json.dumps(BASE))) == []


@pytest.mark.parametrize("key", EXACT_KEYS)
def test_any_exact_key_change_is_detected(key):
    other = {**BASE, key: [{"changed": True}]}
    assert diff_keys(BASE, other) == [key]


def test_term_uses_order_does_not_matter_but_content_does():
    reordered = {**BASE, "term_uses": list(reversed(BASE["term_uses"]))}
    assert diff_keys(BASE, reordered) == []
    dropped = {**BASE, "term_uses": BASE["term_uses"][:1]}
    assert diff_keys(BASE, dropped) == ["term_uses"]
    # 多重集合：同じ要素の重複の数も比べる
    doubled = {**BASE, "term_uses": BASE["term_uses"] + BASE["term_uses"][:1]}
    assert diff_keys(BASE, doubled) == ["term_uses"]


def test_ai_layers_are_not_compared():
    assert "pages" not in EXACT_KEYS + MULTISET_KEYS
    assert diff_keys(BASE, {**BASE, "pages": []}) == []


def test_missing_key_differs_from_empty_value():
    """片方に無いキーは不一致（None と空配列・キーの欠落を区別する）。"""
    without = {k: v for k, v in BASE.items() if k != "parties"}
    assert diff_keys(BASE, without) == ["parties"]


def _write(d, name, obj):
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_compare_dirs_reports_missing_and_mismatch(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a, "d1", BASE)
    _write(b, "d1", BASE)
    _write(a, "d2", BASE)
    _write(b, "d2", {**BASE, "refs": [{"to": "x"}]})
    _write(a, "d3", BASE)
    assert compare_dirs(a, b, ["d1", "d2", "d3"]) == {"d2": ["refs"], "d3": ["片方にしか無い"]}


def test_compare_dirs_ignores_keys_absent_on_one_side_only_when_asked(tmp_path):
    """約款の移植元は契約書の追加キーを出さない。指定したキーだけ、片方に無いときに比べない。"""
    a, b = tmp_path / "a", tmp_path / "b"
    legacy = {
        k: v
        for k, v in BASE.items()
        if k not in ("numbering_scheme", "parties", "defined_terms_detail")
    }
    _write(a, "d1", BASE)
    _write(b, "d1", legacy)
    keys = ("numbering_scheme", "parties", "defined_terms_detail")
    assert compare_dirs(a, b, ["d1"]) == {"d1": list(keys)}
    assert compare_dirs(a, b, ["d1"], ignore_missing_keys=keys) == {}
    # 両方にあれば指定しても比べる（値の違いは見逃さない）
    _write(b, "d1", {**BASE, "parties": [{"alias": "甲"}]})
    assert compare_dirs(a, b, ["d1"], ignore_missing_keys=keys) == {"d1": ["parties"]}


def test_metric_diffs_compares_numbers_by_value():
    """移植元の値は VARIANT を通って 1.0 が 1 になっている。値で比べる。"""
    mine = {"citation": {"citation_error_rate": 0.0, "coverage": 1.0, "n_wrong": 0}}
    ref = {"citation": {"citation_error_rate": 0, "coverage": 1, "n_wrong": 0}}
    assert metric_diffs(mine, ref) == {"value": [], "only_mine": [], "only_ref": []}


def test_metric_diffs_detects_value_change_and_separates_extra_keys():
    mine = {
        "citation": {"n_wrong": 1, "coverage": 0.9},
        "structure": {"nted_doc": {"nted_doc": 0.0}},
    }
    ref = {"citation": {"n_wrong": 0}, "structure": {}, "terms": {"f1": 1.0}}
    assert metric_diffs(mine, ref) == {
        "value": ["/citation/n_wrong"],
        "only_mine": ["/citation/coverage", "/structure/nted_doc"],
        "only_ref": ["/terms"],
    }


class TestCompareDocMetrics:
    def test_family_missing_in_ref_is_not_a_mismatch(self):
        from jpdocread.compare import compare_doc_metrics

        mine = {"d": {"citation": {"n_wrong": 0}, "parties": {"f1": 0.0}, "text": {"cer": 0.1}}}
        ref = {"d": {"citation": {"n_wrong": 0}, "text": {"cer": 0.2}}}
        r = compare_doc_metrics(mine, ref)
        assert r["n_structural_mismatch"] == 0
        assert (
            r["docs"]["d"]["not_in_ref"][:1] == ["structure"]
            and "parties" in r["docs"]["d"]["not_in_ref"]
        )
        assert r["docs"]["d"]["ai_differences"] == ["text/cer"]

    def test_structural_value_difference_is_detected(self):
        from jpdocread.compare import compare_doc_metrics

        r = compare_doc_metrics(
            {"d": {"citation": {"n_wrong": 1}}}, {"d": {"citation": {"n_wrong": 0}}}
        )
        assert r["n_structural_mismatch"] == 1
        assert r["docs"]["d"]["structural_mismatch"] == ["citation/n_wrong"]

    def test_missing_family_on_my_side_is_detected(self):
        """比較先にあって本実装に無い群は不一致（黙って比べないことにしない）。"""
        from jpdocread.compare import compare_doc_metrics

        r = compare_doc_metrics({"d": {}}, {"d": {"refs": {"tp": 3}}})
        assert r["n_structural_mismatch"] == 1

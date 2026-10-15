"""H15 のリファクタリングで切り出した関数の単体テスト（振る舞いは改修前と同じ）。"""

from __future__ import annotations

import pytest

from jpdocread.common.bbox import area, contains, overlap_area, overlap_of_smaller
from jpdocread.config import load_corpus_config
from jpdocread.eval.metrics_figregion import extra_kind, figure_region_scores, match_gold_figures
from jpdocread.jobs import validate_output
from jpdocread.local import read_options
from jpdocread.read.integrate import ReadOptions


class TestBbox:
    def test_area_and_overlap(self):
        assert area([0, 0, 10, 5]) == 50
        assert area([5, 5, 0, 0]) == 0  # 裏返った矩形は 0
        assert overlap_area([0, 0, 10, 10], [5, 5, 20, 20]) == 25
        assert overlap_area([0, 0, 1, 1], [2, 2, 3, 3]) == 0

    def test_overlap_of_smaller(self):
        assert overlap_of_smaller([0, 0, 100, 100], [10, 10, 20, 20]) == 1.0
        assert overlap_of_smaller([0, 0, 0, 0], [0, 0, 0, 0]) == 0.0

    def test_contains_with_tolerance(self):
        assert contains([0, 0, 10, 10], [0, 0, 10, 10])
        assert not contains([0, 0, 10, 10], [-0.6, 0, 10, 10], tol=0.5)
        assert contains([0, 0, 10, 10], [-0.4, 0, 10, 10.4], tol=0.5)


@pytest.mark.parametrize("name", ["yakkan", "contract"])
def test_read_options_come_from_one_place(name):
    """ローカルのワーカーに渡す設定は ReadOptions.from_corpus と同じ（キーの二重定義をしない）。"""
    c = load_corpus_config(name)
    assert ReadOptions(**read_options(c)) == ReadOptions.from_corpus(c)


class TestFigureRegions:
    ELEMENTS = [
        {"kind": "figure", "pages": [1], "bboxes": [[0, 0, 100, 100]]},
        {"kind": "figure", "pages": [2], "bboxes": [[0, 0, 50, 50]]},
        {"kind": "footnote", "pages": [1], "bboxes": [[0, 200, 100, 220]]},
    ]
    PRED = {
        "figure_regions": [
            {"pages": [1], "bbox": [-5, -5, 105, 105]},  # 図 1 に対応
            {"pages": [1], "bbox": [-5, 195, 105, 225]},  # 脚注
            {"pages": [1], "bbox": [300, 300, 400, 400]},  # 何にも重ならない
        ]
    }

    def test_match(self):
        regions = [(r["pages"][0], r["bbox"]) for r in self.PRED["figure_regions"]]
        assert match_gold_figures(self.ELEMENTS, regions) == ({0}, 2, 1)

    def test_extra_kind(self):
        gold = [("footnote", 1, [0, 200, 100, 220]), ("note", 1, [300, 300, 310, 310])]
        assert extra_kind((1, [-5, 195, 105, 225]), gold) == "footnote"
        assert extra_kind((1, [300, 300, 310, 310]), gold) == "other"
        assert extra_kind((2, [0, 0, 1, 1]), gold) == "none"

    def test_scores(self):
        assert figure_region_scores(self.ELEMENTS, self.PRED) == {
            "n_regions": 3,
            "n_gold_figures": 2,
            "n_matched": 1,
            "n_extra": 2,
            "n_gold_missed": 1,
            "extra_by_kind": {"footnote": 1, "none": 1},
        }


class TestValidateOutput:
    def _ok(self):
        from jpdocread.jobs import CONTRACT_KEYS, REQUIRED_KEYS
        from jpdocread.read.integrate import SCHEMA_VERSION

        out = {k: [] for k in (*REQUIRED_KEYS, *CONTRACT_KEYS)}
        out.update(schema_version=SCHEMA_VERSION, numbering_scheme=None)
        return out

    def test_ok(self):
        validate_output(self._ok())

    @pytest.mark.parametrize(
        ("patch", "msg"),
        [
            ({"schema_version": "9.9"}, "schema_version"),
            ({"elements": [{"element_id": "e1"}]}, "elements[]"),
            ({"pages": [{"number": 1}]}, "pages[]"),
            ({"numbering_scheme": "standard", "parties": [{"alias": "甲"}]}, "parties[]"),
        ],
    )
    def test_violations(self, patch, msg):
        out = self._ok()
        out.update(patch)
        with pytest.raises(ValueError, match=msg.replace("[", r"\[").replace("]", r"\]")):
            validate_output(out)

    def test_missing_key(self):
        out = self._ok()
        del out["elements"]
        with pytest.raises(ValueError, match="必須キー"):
            validate_output(out)

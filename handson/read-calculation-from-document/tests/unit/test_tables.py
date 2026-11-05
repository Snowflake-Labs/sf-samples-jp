"""表の自動読み取り：縦向き・横向き・単位つきのキー、数値でない表は例外（合成の pdoc）。"""

from __future__ import annotations

import pytest

from jpcalc.predict import tables as TB
from jpcalc.predict.policy_index import PolicyIndex


def _doc(grid, constants=None):
    return {
        "meta": {"constants": constants or {}},
        "body": [
            {
                "id": "a1",
                "kind": "article",
                "children": [],
                "blocks": [
                    {"type": "table", "id": "t1", "grid": [[{"text": c} for c in r] for r in grid]}
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("grid", "rows"),
    [
        (
            [["等級", "支払割合"], ["第１級", "100%"], ["第２級", "90％"], ["第３級", "80%"]],
            [[1, 100], [2, 90], [3, 80]],
        ),
        (
            [["経過期間", "1年まで", "2年まで", "3年まで"], ["返還率", "70%", "50%", "30%"]],
            [[1, 70], [2, 50], [3, 30]],
        ),
        (
            [["日数", "給付額"], ["30日以下", "3万円"], ["60日以下", "5万円"]],
            [[30, 30000], [60, 50000]],
        ),
    ],
)
def test_auto_layout(grid, rows):
    ix = PolicyIndex(_doc(grid))
    assert TB.read_rows(ix, "t1", **TB.auto_layout(ix, "t1")) == rows


def test_non_numeric_table_raises():
    ix = PolicyIndex(_doc([["区分", "内容"], ["Ａ", "見本の説明"], ["Ｂ", "別の説明"]]))
    with pytest.raises(TB.TableReadError):
        TB.auto_layout(ix, "t1")

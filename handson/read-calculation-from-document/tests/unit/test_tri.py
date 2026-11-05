"""三値論理（Kleene）・厳密な算術・端数処理・表引き・日付・集計の補助関数。"""

from __future__ import annotations

import datetime as dt
import itertools

from jpcalc.common import tri as T

V3 = (True, False, None)


def _k_and(a, b):
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def test_kleene_tables():
    for a, b in itertools.product(V3, V3):
        assert T.t_and(a, b) == _k_and(a, b)
        assert T.t_or(a, b) == T.t_not(_k_and(T.t_not(a), T.t_not(b)))
    for a, b, c in itertools.product(V3, V3, V3):  # 27 通り
        assert T.t_and(a, b, c) == _k_and(_k_and(a, b), c)


def test_strict_arith():
    assert T.t_add(1, None) is None and T.t_min(3, None) is None and T.t_mul(0, None) is None
    assert T.t_cmp("ge", None, 1) is None and T.t_cmp("gt", 2, 1) is True
    assert T.t_sub(5, 7) == -2


def test_muldiv_round():
    assert T.t_muldiv(7, 3, 2, "floor") == 10 and T.t_muldiv(7, 3, 2, "ceil") == 11
    assert T.t_muldiv(5, 1, 2, "half_up") == 3 and T.t_muldiv(1, 1, 0) is None
    assert T.t_round_to(12345, 1000, "floor") == 12000 and T.t_round_to(12345, 0) is None
    assert T.t_round_to(12500, 1000, "half_up") == 13000


def test_if_lazy_and_unknown():
    assert T.t_if(None, lambda: 1, lambda: 2) is None
    assert T.t_if(True, lambda: 1, lambda: 1 / 0) == 1


def test_lookup():
    rows = ((2, 90), (4, 80), (6, 70))
    assert T.t_lookup(rows, 4, "exact") == 80 and T.t_lookup(rows, 3, "exact") is None
    assert T.t_lookup(rows, 3, "step_le") == 80 and T.t_lookup(rows, 7, "step_le") is None
    assert T.t_lookup(rows, None) is None


def test_dates():
    assert T.t_add_months(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
    assert T.t_add_months(dt.date(2023, 1, 31), 1) == dt.date(2023, 2, 28)
    assert T.t_add_months(dt.date(2023, 11, 30), 3) == dt.date(2024, 2, 29)
    assert T.t_end_of_month(dt.date(2024, 2, 3)) == dt.date(2024, 2, 29)
    assert T.t_add_days(dt.date(2024, 12, 31), 1) == dt.date(2025, 1, 1)
    assert T.t_days_between(dt.date(2024, 1, 1), dt.date(2024, 3, 1)) == 60
    assert T.t_add_days(None, 1) is None


def test_agg():
    items = [{"x": 1}, {"x": 2}]
    assert T.t_agg("sum", items, lambda it: T.t_item(it, "x")) == 3
    assert T.t_agg("sum", [{"x": 1}, {"x": None}], lambda it: T.t_item(it, "x")) is None
    assert T.t_agg("sum", None, lambda it: 0) is None
    assert T.t_agg("sum", [], lambda it: 0) == 0

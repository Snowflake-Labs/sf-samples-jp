"""数値パーサ：全角・半角、円と万円、率、日・月・年、範囲、往復、解析できない表記。"""

from __future__ import annotations

import datetime as dt
from fractions import Fraction

import pytest

from jpcalc.common import numparse as N


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("1万円", 10_000, "JPY"),
        ("75,000円", 75_000, "JPY"),
        ("３，０００万円", 30_000_000, "JPY"),
        ("9億9，999万円", 999_990_000, "JPY"),
        ("9万9千円", 99_000, "JPY"),
        ("1.5万円", 15_000, "JPY"),
        ("日額5,000円", 5_000, "JPY"),
        ("30日", 30, "DAY"),
        ("１０営業日", 10, "BUSINESS_DAY"),
        ("6か月", 6, "MONTH"),
        ("６ヶ月", 6, "MONTH"),
        ("満3年", 3, "YEAR"),
        ("30%", 30, "PERCENT"),
        ("年1.25％", Fraction(5, 4), "PERCENT"),
        ("１４．６％", Fraction(73, 5), "PERCENT"),
        ("３割", 30, "PERCENT"),
        ("三割", 30, "PERCENT"),
        ("2割5分", 25, "PERCENT"),
        ("1.5倍", Fraction(3, 2), "TIMES"),
        ("3回", 3, "COUNT"),
        ("2名", 2, "PERSON"),
        ("8時間", 8, "HOUR"),
        ("30分", 30, "MINUTE"),
        ("満20歳", 20, "AGE"),
        ("第3級", 3, "GRADE"),
        ("無制限", 0, "UNLIMITED"),
    ],
)
def test_parse(text, value, unit):
    q = N.parse(text)
    assert (q.value, q.unit) == (value, unit)


def test_fullwidth_equals_halfwidth():
    assert N.parse("１２，３４５円") == N.parse("12,345円")
    assert N.parse("　３０日 ") == N.parse("30日")


@pytest.mark.parametrize("text", ["", "円", "abc", "1.5円", "三十日", "30", "1,2,3x", "１０営業"])
def test_parse_errors(text):
    with pytest.raises(N.NumParseError):
        N.parse(text)


@pytest.mark.parametrize(
    "q",
    [
        N.Qty(10_000, "JPY"),
        N.Qty(1_500, "JPY"),
        N.Qty(30_000_000, "JPY"),
        N.Qty(30, "DAY"),
        N.Qty(10, "BUSINESS_DAY"),
        N.Qty(6, "MONTH"),
        N.Qty(3, "YEAR"),
        N.Qty(30, "PERCENT"),
        N.Qty(Fraction(5, 4), "PERCENT"),
        N.Qty(Fraction(3, 2), "TIMES"),
        N.Qty(3, "COUNT"),
        N.Qty(8, "HOUR"),
        N.Qty(20, "AGE"),
        N.Qty(3, "GRADE"),
    ],
)
def test_round_trip(q):
    assert N.parse(N.format_qty(q)) == q


def test_range():
    r = N.parse_range("60%以上80%未満")
    assert (r.low, r.low_inclusive, r.high, r.high_inclusive) == (
        N.Qty(60, "PERCENT"),
        True,
        N.Qty(80, "PERCENT"),
        False,
    )
    r = N.parse_range("５日を超える")
    assert (r.low, r.low_inclusive, r.high) == (N.Qty(5, "DAY"), False, None)
    r = N.parse_range("満6歳から満70歳まで")
    assert (r.low.value, r.high.value, r.low_inclusive, r.high_inclusive) == (6, 70, True, True)
    with pytest.raises(N.NumParseError):
        N.parse_range("おおむね5日")


def test_parse_date():
    assert N.parse_date("２０３０年７月１日") == dt.date(2030, 7, 1)
    assert N.parse_date("2026-02-26") == dt.date(2026, 2, 26)

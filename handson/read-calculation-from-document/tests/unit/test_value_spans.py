"""値スパンの逆対照：年月日の日付は数値の値スパンにしない。漢数字の数値表記は数えるだけ。"""

import pytest

from jpcalc.pdfread.pdoc import Values


@pytest.mark.parametrize(
    "text",
    [
        "2026年4月1日から",
        "２０２６年４月１日から",
        "令和7年10月1日に",
        "令和元年5月1日",
        "平成31年4月30日まで",
        "2026年4月分",
        "毎年4月1日に更新",
        "2026年度",
        "令和8年度",
        "令和8年",
        "平成元年",
        "２０２６年",
    ],
)
def test_dates_stay_verbatim(text):
    v = Values()
    assert v.sub(text, "t") == text
    assert v.constants == {} and v.n_dates == 1


def test_values_around_a_date_are_still_spans():
    v = Values()
    out = v.sub("2026年4月1日から30日以内に1万円を支払う", "t")
    assert out == "2026年4月1日から{const:v001}以内に{const:v002}を支払う"
    assert v.constants == {"v001": "30日", "v002": "1万円"} and v.n_dates == 1


@pytest.mark.parametrize(
    "text",
    ["毎月25日までに", "3年以内", "1日につき", "第3級", "保険期間10年", "12345年"],
)
def test_non_dates_are_unchanged_by_the_date_rule(text):
    v = Values()
    v.sub(text, "t")
    assert v.n_dates == 0


def test_kanji_values_are_counted_not_converted():
    v = Values()
    assert v.sub("十万円を限度に三十日以内", "t") == "十万円を限度に三十日以内"
    assert v.n_kanji == 2 and v.constants == {}
    v2 = Values()
    v2.sub("第三条に定める", "t")
    assert v2.n_kanji == 0


@pytest.mark.parametrize("text", ["十分に注意する", "三分の一を支払う"])
def test_words_with_kanji_numbers_are_not_counted(text):
    v = Values()
    v.sub(text, "t")
    assert v.n_kanji == 0


def test_a_date_right_after_a_form_number_is_kept():
    v = Values()
    assert (
        v.sub("様式Ｓ２６１００２2026年10月1日改定", "t") == "様式Ｓ２６１００２2026年10月1日改定"
    )
    assert v.n_dates == 1 and v.constants == {}

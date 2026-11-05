"""約款・契約書の数値表記の決定的パーサ。

金額（1万円・75,000円・３，０００万円・9億9，999万円・9万9千円）・日数（30日・3営業日）・
月数（6か月）・年数（3年・満3年）・割合（30%・３割・年1.25％）・倍率（1.5倍）・回数・人数・時間・距離・年齢を
(値, 単位) に変換する。全角数字・全角カンマ・全角ピリオドを受け付ける。解析できない表記は NumParseError。
範囲（「以上」「未満」など）は parse_range で扱う。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

_Z2H = str.maketrans("０１２３４５６７８９，．％－", "0123456789,.%-")
_KANSUJI = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class NumParseError(ValueError):
    pass


@dataclass(frozen=True)
class Qty:
    value: int | Fraction
    unit: str  # JPY / DAY / BUSINESS_DAY / MONTH / YEAR / PERCENT / RATIO / TIMES / COUNT / PERSON / HOUR / MINUTE / KM / AGE / UNLIMITED


def _num(s: str) -> int | Fraction:
    s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise NumParseError(f"not a number: {s!r}")
    if "." in s:
        f = Fraction(s)
        return int(f) if f.denominator == 1 else f
    return int(s)


def _yen(s: str) -> int:
    """億・万・千・円の組合せ。例 9億9,999万円・9万9千円・3,000万円・1,500円。"""
    m = re.fullmatch(
        r"(?:(?P<oku>[\d,.]+)億)?(?:(?P<man>[\d,.]+)万)?(?:(?P<sen>[\d,.]+)千)?(?P<en>[\d,.]+)?円",
        s,
    )
    if not m or not any(m.groupdict().values()):
        raise NumParseError(f"not an amount: {s!r}")
    total = Fraction(0)
    for k, mult in (("oku", 10**8), ("man", 10**4), ("sen", 10**3), ("en", 1)):
        if m.group(k):
            total += Fraction(_num(m.group(k))) * mult
    if total.denominator != 1:
        raise NumParseError(f"fractional yen: {s!r}")
    return int(total)


_UNITS = (
    (r"営業日", "BUSINESS_DAY"),
    (r"日", "DAY"),
    (r"か月|ヶ月|カ月|箇月", "MONTH"),
    (r"年", "YEAR"),
    (r"%", "PERCENT"),
    (r"割", "TENTH"),
    (r"倍", "TIMES"),
    (r"回", "COUNT"),
    (r"名|人", "PERSON"),
    (r"時間", "HOUR"),
    (r"分", "MINUTE"),
    (r"キロメートル|km", "KM"),
    (r"歳", "AGE"),
    (r"級", "GRADE"),
    (r"台", "UNIT"),
    (r"つ|個|件", "COUNT"),
)


def parse(text: str) -> Qty:
    s = text.strip().translate(_Z2H).replace(" ", "").replace("\u3000", "")
    if s in ("無制限", "限度なし"):
        return Qty(0, "UNLIMITED")
    s = re.sub(r"^(日額|年額|月額|年間|満|最大|最高)", "", s)
    if m := re.fullmatch(r"([\d]+)割([\d]+)分", s):
        return Qty(int(m.group(1)) * 10 + int(m.group(2)), "PERCENT")
    if s.startswith("年") and re.fullmatch(r"年[\d,.]+%", s):
        s = s[1:]
    if s.endswith("円"):
        return Qty(_yen(s), "JPY")
    if m := re.fullmatch(r"第?([\d,.]+)級", s):
        return Qty(_num(m.group(1)), "GRADE")
    if m := re.fullmatch(r"([一二三四五六七八九十])割", s):
        return Qty(_KANSUJI[m.group(1)] * 10, "PERCENT")
    for pat, unit in _UNITS:
        if m := re.fullmatch(r"([\d,.]+)(?:" + pat + r")", s):
            v = _num(m.group(1))
            if unit == "TENTH":
                return Qty(v * 10, "PERCENT")
            return Qty(v, unit)
    raise NumParseError(f"unparsed: {text!r}")


@dataclass(frozen=True)
class Range:
    low: Qty | None
    low_inclusive: bool
    high: Qty | None
    high_inclusive: bool


_BOUND = re.compile(r"(?P<q>.+?)(?P<rel>以上|を超える|超|以下|未満)")


def parse_range(text: str) -> Range:
    """「60%以上80%未満」「満20歳以上満70歳以下」「2年以下」「5日を超える」「満6歳から満70歳まで」。"""
    s = text.strip().translate(_Z2H)
    if m := re.fullmatch(r"(.+?)から(.+?)まで", s):
        return Range(parse(m.group(1)), True, parse(m.group(2)), True)
    parts = list(_BOUND.finditer(s))
    if not parts or "".join(p.group(0) for p in parts) != s:
        raise NumParseError(f"not a range: {text!r}")
    low = high = None
    li = hi = False
    for p in parts:
        q, rel = parse(p.group("q")), p.group("rel")
        if rel == "以上":
            low, li = q, True
        elif rel in ("を超える", "超"):
            low, li = q, False
        elif rel == "以下":
            high, hi = q, True
        else:
            high, hi = q, False
    return Range(low, li, high, hi)


def format_qty(q: Qty) -> str:
    """数値 → 文言（往復テスト用の正準形）。"""
    v = q.value
    if q.unit == "JPY":
        if v and v % 10**4 == 0:
            return f"{v // 10**4:,}万円"
        return f"{v:,}円"
    suffix = {
        "DAY": "日",
        "BUSINESS_DAY": "営業日",
        "MONTH": "か月",
        "YEAR": "年",
        "PERCENT": "%",
        "TIMES": "倍",
        "COUNT": "回",
        "PERSON": "名",
        "HOUR": "時間",
        "MINUTE": "分",
        "KM": "キロメートル",
        "AGE": "歳",
        "GRADE": "級",
        "UNIT": "台",
    }[q.unit]
    return f"{float(v):g}{suffix}" if isinstance(v, Fraction) else f"{v}{suffix}"


def parse_date(text: str):
    """2026年2月26日 / 2026-02-26 → datetime.date。"""
    import datetime as dt

    s = text.strip().translate(_Z2H)
    if m := re.fullmatch(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s):
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise NumParseError(f"not a date: {text!r}")

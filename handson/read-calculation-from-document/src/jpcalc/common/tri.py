"""三値論理と厳密計算の補助関数（生成コードと参照インタプリタが共通に使う）。

タスクカードの conventions の文面から実装した：
- 判定（and / or / not）は Kleene の三値論理。ほかの条件だけで結論が決まれば確定値を返す
- 計算（加減乗除・比較・表引き・日付計算）は厳密。不明（None）が混じれば結果も不明
- if は条件が不明なら不明。選ばれなかった枝は評価しない（遅延評価）
- 表に無いキーは不明

このファイルは標準ライブラリだけに依存し、codegen が生成モジュールにそのまま埋め込む（単体で動かすため）。
"""

import calendar as _calendar
import datetime as _dt


def _any_none(*xs):
    return any(x is None for x in xs)


def t_add(*xs):
    return None if _any_none(*xs) else sum(xs)


def t_sub(a, b):
    return None if _any_none(a, b) else a - b


def t_mul(*xs):
    if _any_none(*xs):
        return None
    out = 1
    for x in xs:
        out *= x
    return out


def t_min(*xs):
    return None if _any_none(*xs) else min(xs)


def t_max(*xs):
    return None if _any_none(*xs) else max(xs)


def _div_round(n, d, rounding):
    if rounding == "floor":
        return n // d
    if rounding == "ceil":
        return -((-n) // d)
    if rounding == "half_up":
        q, r = divmod(n, d)
        return q + (1 if 2 * r >= d else 0)
    raise ValueError(f"unknown rounding: {rounding}")


def t_muldiv(a, b, c, rounding="floor"):
    """a×b÷c を整数で返す。c が 0 なら不明。"""
    if _any_none(a, b, c) or c == 0:
        return None
    n = a * b
    if c < 0:
        n, c = -n, -c
    if isinstance(n, int) and isinstance(c, int):
        return _div_round(n, c, rounding)
    from fractions import Fraction

    q = Fraction(n) / Fraction(c)
    return _div_round(q.numerator, q.denominator, rounding)


def t_round_to(x, unit, rounding="floor"):
    """x を unit の倍数に丸める。unit が 0 以下なら不明。"""
    if _any_none(x, unit) or unit <= 0:
        return None
    return _div_round(x, unit, rounding) * unit


def t_cmp(op, a, b):
    if _any_none(a, b):
        return None
    return {"ge": a >= b, "gt": a > b, "le": a <= b, "lt": a < b, "eq": a == b, "ne": a != b}[op]


def t_and(*xs):
    if any(x is False for x in xs):
        return False
    return None if _any_none(*xs) else True


def t_or(*xs):
    if any(x is True for x in xs):
        return True
    return None if _any_none(*xs) else False


def t_not(x):
    return None if x is None else (not x)


def t_if(cond, then_fn, else_fn):
    if cond is None:
        return None
    return then_fn() if cond else else_fn()


def t_coalesce(*fns):
    for f in fns:
        v = f()
        if v is not None:
            return v
    return None


def t_lookup(rows, key, mode="exact"):
    """rows は (key, value) の列。exact は一致、step_le はキー以上で最小の行（キーの昇順で並べておく）。"""
    if key is None:
        return None
    if mode == "exact":
        for k, v in rows:
            if k == key:
                return v
        return None
    if mode == "step_le":
        for k, v in sorted(rows, key=lambda r: r[0]):
            if key <= k:
                return v
        return None
    if mode == "step_ge":
        best = None
        for k, v in sorted(rows, key=lambda r: r[0]):
            if key >= k:
                best = v
        return best
    raise ValueError(f"unknown lookup mode: {mode}")


def t_add_days(d, n):
    return None if _any_none(d, n) else d + _dt.timedelta(days=n)


def t_add_months(d, n):
    if _any_none(d, n):
        return None
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return _dt.date(y, m, min(d.day, _calendar.monthrange(y, m)[1]))


def t_end_of_month(d):
    if d is None:
        return None
    return _dt.date(d.year, d.month, _calendar.monthrange(d.year, d.month)[1])


def t_days_between(a, b):
    """b − a の日数（後 − 前）。"""
    return None if _any_none(a, b) else (b - a).days


def t_agg(func, items, fn):
    """明細の集計。items が不明なら不明。各明細の値は厳密（1 件でも不明なら不明）。"""
    if items is None:
        return None
    vals = [fn(it) for it in items]
    if func == "count":
        return len(vals)
    if _any_none(*vals):
        return None
    if func == "sum":
        return sum(vals)
    if func == "max":
        return max(vals) if vals else None
    if func == "min":
        return min(vals) if vals else None
    raise ValueError(f"unknown agg func: {func}")


def t_item(it, field):
    if it is None:
        return None
    return it.get(field) if isinstance(it, dict) else None

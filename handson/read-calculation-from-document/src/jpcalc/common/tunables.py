"""調整できる値の読み出し口（決定的な段の閾値・語の一覧）。

本体のコードは定数を `tun("<名前>", <今の値>)` で読む。上書きが無ければ今の値をそのまま返すので、
通常の実行（予測・SPCS ジョブ・CLI）の結果は変わらない。上書きは `override({...})` の文脈の中でだけ効き、
環境変数・設定ファイル・CLI からは効かない。最適化の検証（拡張パッケージ）だけが使う。

文脈の中で読まれた名前は記録するので、上書きしたのに一度も読まれなかった名前（綴りの誤りなど）を
`override` を抜けるときに検出できる（strict=True で例外）。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

T = TypeVar("T")


class TunableError(KeyError):
    pass


_OVR: ContextVar[Mapping[str, Any] | None] = ContextVar("jpcalc_tunables", default=None)
_SEEN: ContextVar[set[str] | None] = ContextVar("jpcalc_tunables_seen", default=None)


def tun(name: str, default: T) -> T:
    """name の値。上書きの文脈の外、または上書きに name が無ければ default をそのまま返す。"""
    ovr = _OVR.get()
    if ovr is None:
        return default
    seen = _SEEN.get()
    if seen is not None:
        seen.add(name)
    return ovr.get(name, default)


def active() -> bool:
    """上書きの文脈の中か。"""
    return _OVR.get() is not None


@contextmanager
def override(values: Mapping[str, Any], *, strict: bool = True) -> Iterator[set[str]]:
    """values で上書きする文脈。戻り値は文脈の中で読まれた名前の集合。

    strict なら、抜けるときに読まれなかった上書きの名前があれば TunableError。
    入れ子にすると内側の値が外側に重なる。
    """
    outer = _OVR.get() or {}
    tok = _OVR.set({**outer, **dict(values)})
    seen: set[str] = set()
    tok_s = _SEEN.set(seen)
    ok = False
    try:
        yield seen
        ok = True
    finally:
        _OVR.reset(tok)
        _SEEN.reset(tok_s)
    if ok and strict:
        unused = sorted(set(values) - seen)
        if unused:
            raise TunableError(f"上書きしたが読まれなかった名前: {', '.join(unused)}")


# ---------------------------------------------------------------- 許可表

# 本体が `tun` で読む名前と、値の型（既定値の型）。設定ファイルの `tuning:` など、文脈の外から渡す値は
# validate で検査する。`override` は表を見ない（検証の拡張が試しの名前を使えるようにするため）。
# 表と本体の `tun("…")` の呼び出しの一致は単体テストが走査で確かめる。
_F, _I, _S = (float, int), (int,), (list, tuple, set, frozenset)
KNOWN: dict[str, tuple[type, ...]] = {
    **{
        f"geom.{k}": _F
        for k in (
            "contract_fig_min_h",
            "fig_grow_merge_gap",
            "fig_grow_pad",
            "fig_merge_gap",
            "fig_min_area",
            "fig_min_seg",
            "fig_table_overlap",
            "gutter_min_band",
            "gutter_thr",
            "gutter_thr_fallback",
            "table_merge_gap",
            "y_tol",
        )
    },
    # pdfplumber の find_tables の設定（geometry.TABLE_SETTING_KEYS。名前を組み立てて読む）
    **{
        f"table.{k}": _F
        for k in ("snap_tolerance", "join_tolerance", "intersection_tolerance", "edge_min_length")
    },
    **{
        f"pdoc.{k}": _I
        for k in (
            "formula_hslack",
            "formula_max_h",
            "formula_min_h",
            "formula_min_w",
            "formula_vgap",
            "formula_word_pad",
            "frame_min_h",
            "frame_min_w",
            "header_rule_cov_tol",
            "header_rule_gap",
            "light_min_h",
            "light_min_w",
        )
    },
    "pdoc.light_lum_lo": _F,
    "pdoc.semtype_frac": _F,
    "j1.cues": _S,
    "j1.cues_extra": _S,
    "j1.deadline_patterns": _S,
    "j1.rule_figures": _S,
    "j1.rule_tables": _S,
    "j1.title_cues": _S,
    "j1.table_max_rows": _I,
}


def validate(values: Mapping[str, Any]) -> list[str]:
    """文脈の外から渡す上書き（設定ファイルの tuning: など）の検査。問題の一覧（空なら通る）。

    名前は KNOWN にあること、値の型が KNOWN の型であること（数値の int は float にも可。bool は数値にしない）。
    一覧の型の要素は文字列であること。
    """
    probs = []
    for k, v in values.items():
        if k not in KNOWN:
            probs.append(f"未知の名前: {k}")
            continue
        ty = KNOWN[k]
        if isinstance(v, bool) or not isinstance(v, ty):
            probs.append(f"{k}: 型が違う（{type(v).__name__}）")
        elif ty is _S and not all(isinstance(x, str) for x in v):
            probs.append(f"{k}: 要素は文字列")
    return probs

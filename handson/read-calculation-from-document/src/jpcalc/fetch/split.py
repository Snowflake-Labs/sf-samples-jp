"""DEV/HOLDOUT の分割（base 単位・層別・ハッシュ順。決定的）。

入力は公開索引の列（文書 ID・base・層）だけで、正解を読まない。
同じ base から作った文書・体裁はすべて同じ側に入る。層ごとに base を `sha256(salt + base)` の 16 進表記の
昇順に並べ、先頭の `round(層の base 数 × dev_fraction)` 件を DEV にする（Python の round）。
base 一覧の照合値は、base を昇順に並べて改行で連結した文字列（末尾の改行なし）の SHA-256。
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import yaml

from ..common.paths import CONFIGS

SPLIT_YAML = CONFIGS / "split.yaml"
SIDES = ("dev", "holdout")


class SplitError(RuntimeError):
    """分割の設定・再計算が一致しない。"""


def bases_sha256(bases: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(bases)).encode("utf-8")).hexdigest()


def compute_split(rows: Iterable[dict], *, salt: str, dev_fraction: float) -> dict[str, list[str]]:
    """公開索引の行から、DEV と HOLDOUT の base 一覧（昇順）を返す。"""
    by_stratum: dict[str, set[str]] = defaultdict(set)
    stratum_of: dict[str, str] = {}
    for r in rows:
        base, stratum = r["split_group"], r["stratum"]
        if stratum_of.setdefault(base, stratum) != stratum:
            raise SplitError(f"base {base} が複数の層に属する: {stratum_of[base]} と {stratum}")
        by_stratum[stratum].add(base)
    dev: set[str] = set()
    for bases in by_stratum.values():
        ordered = sorted(
            bases, key=lambda b: hashlib.sha256((salt + b).encode("utf-8")).hexdigest()
        )
        dev |= set(ordered[: round(len(ordered) * dev_fraction)])
    holdout = set(stratum_of) - dev
    return {"dev": sorted(dev), "holdout": sorted(holdout)}


def summarize(
    rows: list[dict], split: dict[str, list[str]], *, revision: str, salt: str, dev_fraction: float
) -> dict:
    out: dict = {"revision": revision, "salt": salt, "dev_fraction": dev_fraction}
    for side in SIDES:
        bases = set(split[side])
        docs = [r for r in rows if r["split_group"] in bases]
        out[side] = {
            "n_bases": len(bases),
            "n_docs": len(docs),
            "n_pdfs": sum(len(r["pdfs"]) for r in docs),
            "sha256": bases_sha256(bases),
            "bases": sorted(bases),
        }
    return out


def load_split(path: Path = SPLIT_YAML) -> dict:
    if not path.is_file():
        raise SplitError(f"分割の設定が無い: {path}（`jpcalc split` で作る）")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_split(entries: dict[str, dict], path: Path = SPLIT_YAML) -> None:
    head = (
        "# DEV/HOLDOUT の分割（`jpcalc split` が公開索引から生成する。手で編集しない）。\n"
        "# 同じ base の文書・体裁はすべて同じ側に入る。sha256 は base 一覧（昇順・改行区切り）の照合値。\n"
    )
    body = yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(head + body, encoding="utf-8")


def check_split(corpus: str, recomputed: dict, recorded: dict) -> None:
    """記録した分割と再計算した分割が一致しなければ止める。"""
    have = recorded.get(corpus)
    if have is None:
        raise SplitError(f"{corpus}: configs/split.yaml に記録が無い（`jpcalc split` で作る）")
    for key in ("revision", "salt", "dev_fraction"):
        if have.get(key) != recomputed[key]:
            raise SplitError(
                f"{corpus}: {key} が違う（記録 {have.get(key)!r}・設定 {recomputed[key]!r}）"
            )
    for side in SIDES:
        a, b = have.get(side, {}), recomputed[side]
        if a.get("bases") != b["bases"] or a.get("sha256") != b["sha256"]:
            raise SplitError(f"{corpus}: {side} の base 一覧が再計算と一致しない")
    inter = set(have["dev"]["bases"]) & set(have["holdout"]["bases"])
    if inter:
        raise SplitError(f"{corpus}: DEV と HOLDOUT が重なっている: {sorted(inter)[:5]}")

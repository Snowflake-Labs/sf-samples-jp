"""対象文書の決定。

指定は `--docs`・`--docs-file`・`--slice` のいずれか 1 つ。どれも無ければ既定のスライス（pilot）。
2 つ以上の同時指定はエラーにする（どれかを黙って捨てない）。
未知の doc_id・status が ready でない文書・未知のスライスはエラーで止める。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config import ALL_SLICE, CorpusConfig, PipelineConfig
from .manifest import Manifest


class SelectionError(ValueError):
    """対象文書の指定が不正。"""


@dataclass(frozen=True)
class Selection:
    corpus: str
    how: str  # "docs" | "docs_file" | "slice:<name>"
    doc_ids: tuple[str, ...]
    eval_excluded: tuple[str, ...]  # 対象のうち評価から除外される文書（読み取りはする）
    pages: int
    gold_figures: int
    estimated_credits: float
    needs_confirmation: bool

    def as_dict(self) -> dict:
        return {
            "corpus": self.corpus,
            "how": self.how,
            "n_docs": len(self.doc_ids),
            "doc_ids": list(self.doc_ids),
            "eval_excluded": list(self.eval_excluded),
            "pages": self.pages,
            "gold_figures": self.gold_figures,
            "estimated_credits": round(self.estimated_credits, 2),
            "needs_confirmation": self.needs_confirmation,
        }


def parse_docs_arg(value: str) -> list[str]:
    return [d.strip() for d in value.split(",") if d.strip()]


def read_docs_file(path: Path) -> list[str]:
    """1 行 1 doc_id。`#` 以降はコメント、空行は無視する。"""
    if not path.exists():
        raise SelectionError(f"--docs-file が無い: {path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _dedupe(ids: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for d in ids:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def estimate_credits(
    pages: int, gold_figures: int, pipeline: PipelineConfig, corpus: CorpusConfig
) -> float:
    """見込みクレジット（目安）。図の呼び出し数は、正解の図の数 × 検出される領域の比で見積もる。

    正解の図の数を使うのは見積もりの表示だけで、読み取り（予測経路）には使わない。
    """
    calls = gold_figures * corpus.cost.figure_regions_per_gold_figure
    return (
        pages * pipeline.cost.parse_layout_credits_per_page
        + calls * pipeline.cost.figure_credits_per_call
    )


def select_docs(
    manifest: Manifest,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    *,
    docs: str | None = None,
    docs_file: Path | None = None,
    slice_name: str | None = None,
) -> Selection:
    # 空文字の --docs も「指定あり」とみなす（黙って既定のスライスに切り替えない）
    given = [
        k
        for k, v in (("--docs", docs), ("--docs-file", docs_file), ("--slice", slice_name))
        if v is not None
    ]
    if len(given) > 1:
        raise SelectionError(f"対象文書の指定は 1 つだけにする（同時に指定: {', '.join(given)}）")

    if docs is not None:
        how, ids = "docs", parse_docs_arg(docs)
    elif docs_file is not None:
        how, ids = "docs_file", read_docs_file(docs_file)
    else:
        name = pipeline.defaults.slice if slice_name is None else slice_name
        how = f"slice:{name}"
        if name == ALL_SLICE:
            ids = manifest.ready_ids()
        elif name in corpus.slices:
            ids = list(corpus.slices[name])
        else:
            known = sorted([ALL_SLICE, *corpus.slices])
            raise SelectionError(f"{corpus.name} にスライス {name!r} が無い。選べるもの: {known}")
        slice_name = name

    ids = _dedupe(ids)
    if not ids:
        raise SelectionError("対象文書が 0 件（--docs・--docs-file・--slice の指定を確かめる）")
    unknown = [d for d in ids if d not in manifest.documents]
    not_ready = [
        f"{d}（{manifest.documents[d].status}）"
        for d in ids
        if d in manifest.documents and not manifest.documents[d].ready
    ]
    if unknown or not_ready:
        parts = []
        if unknown:
            parts.append(f"manifest に無い: {', '.join(unknown)}")
        if not_ready:
            parts.append(f"ready でない: {', '.join(not_ready)}")
        raise SelectionError("対象にできない文書がある。" + " / ".join(parts))

    entries = [manifest.documents[d] for d in ids]
    pages = sum(e.pages for e in entries)
    figures = sum(e.figures for e in entries)
    excluded = set(corpus.eval_excluded)
    return Selection(
        corpus=corpus.name,
        how=how,
        doc_ids=tuple(ids),
        eval_excluded=tuple(d for d in ids if d in excluded),
        pages=pages,
        gold_figures=figures,
        estimated_credits=estimate_credits(pages, figures, pipeline, corpus),
        needs_confirmation=bool(slice_name and slice_name in pipeline.defaults.confirm_slices),
    )

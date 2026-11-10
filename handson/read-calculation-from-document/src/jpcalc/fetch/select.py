"""対象の選択（--docs／--docs-file／--slice のどれか 1 つ）。

- 指定は文書 ID（その文書の全体裁）か PDF ID。未知の ID は止める。
- HOLDOUT の PDF は allow_holdout を明示しない限り返さない（--slice holdout も同じ）。
- slice は dev・holdout（分割から）と、pilot・shots（configs/pipeline.yaml）。pilot・shots は DEV でなければ止め、
  pilot と shots が base を共有していても止める（手本の文書が評価の文書と同じ内容にならないように）。
- dev は、手本（shots）と base を共有する PDF を除く（手本は shots の正解から作るので、同じ内容の文書を評価しない）。
- 両コーパスの公開索引には文書の状態（ready など）の列が無いので、状態による除外はしない。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .adapters import PdfRef

SLICES = ("pilot", "shots", "dev", "holdout")


class SelectError(ValueError):
    """対象の指定が不正。"""


def _parse_ids(text: str) -> list[str]:
    ids = [t.strip() for t in text.replace("\n", ",").split(",")]
    return [i for i in ids if i and not i.startswith("#")]


def read_docs_file(path: Path) -> list[str]:
    if not path.is_file():
        raise SelectError(f"--docs-file が無い: {path}")
    lines = [ln.split("#", 1)[0] for ln in path.read_text(encoding="utf-8").splitlines()]
    return _parse_ids(",".join(lines))


def select(
    refs: Sequence[PdfRef],
    split: dict,
    *,
    docs: str | None = None,
    docs_file: Path | None = None,
    slice_name: str | None = None,
    slice_lists: dict[str, Sequence[str]] | None = None,
    allow_holdout: bool = False,
) -> list[PdfRef]:
    given = [x for x in (docs, docs_file, slice_name) if x]
    if len(given) != 1:
        raise SelectError("--docs・--docs-file・--slice のどれか 1 つだけを指定する")
    holdout_bases = set(split["holdout"]["bases"])
    dev_bases = set(split["dev"]["bases"])
    by_pdf = {r.pdf_id: r for r in refs}
    by_doc: dict[str, list[PdfRef]] = {}
    for r in refs:
        by_doc.setdefault(r.doc_id, []).append(r)

    if slice_name:
        if slice_name not in SLICES:
            raise SelectError(f"未知の slice: {slice_name}（{' | '.join(SLICES)}）")
        if slice_name in ("dev", "holdout"):
            bases = dev_bases if slice_name == "dev" else holdout_bases
            if slice_name == "dev":
                bases = bases - shot_bases(refs, (slice_lists or {}).get("shots", ()))
            picked = [r for r in refs if r.split_group in bases]
        else:
            ids = list((slice_lists or {}).get(slice_name, ()))
            if not ids:
                raise SelectError(
                    f"slice {slice_name} が空（configs/pipeline.yaml の slices を確かめる）"
                )
            picked = _resolve(ids, by_pdf, by_doc)
            outside = [r.pdf_id for r in picked if r.split_group not in dev_bases]
            if outside:
                raise SelectError(f"slice {slice_name} に DEV でない PDF がある: {outside}")
            check_slices_disjoint(refs, slice_lists or {})
    else:
        ids = _parse_ids(docs) if docs else read_docs_file(docs_file)
        if not ids:
            raise SelectError("対象の ID が空")
        picked = _resolve(ids, by_pdf, by_doc)

    held = [r.pdf_id for r in picked if r.split_group in holdout_bases]
    if held and not allow_holdout:
        raise SelectError(
            f"HOLDOUT の PDF {len(held)} 件が含まれる（{held[:3]}…）。"
            "HOLDOUT は凍結・費用の宣言・承認の後にだけ、明示の指定で使う"
        )
    seen: set[str] = set()
    return [r for r in picked if not (r.pdf_id in seen or seen.add(r.pdf_id))]


def shot_bases(refs: Sequence[PdfRef], shots: Sequence[str]) -> set[str]:
    """手本（shots）の PDF の base。"""
    by_pdf = {r.pdf_id: r for r in refs}
    by_doc: dict[str, list[PdfRef]] = {}
    for r in refs:
        by_doc.setdefault(r.doc_id, []).append(r)
    return {r.split_group for r in _resolve(list(shots), by_pdf, by_doc)} if shots else set()


def shot_overlap(refs: Sequence[PdfRef], pdf_ids: Sequence[str], shots: Sequence[str]) -> list[str]:
    """対象のうち、手本と base を共有する PDF（手本を使う run の対象にしてはならない）。"""
    bases = shot_bases(refs, shots)
    return [r.pdf_id for r in refs if r.pdf_id in set(pdf_ids) and r.split_group in bases]


def check_slices_disjoint(refs: Sequence[PdfRef], slice_lists: dict[str, Sequence[str]]) -> None:
    """pilot と shots が base を共有しないこと。"""
    by_pdf = {r.pdf_id: r for r in refs}
    by_doc: dict[str, list[PdfRef]] = {}
    for r in refs:
        by_doc.setdefault(r.doc_id, []).append(r)
    bases = {
        k: {r.split_group for r in _resolve(list(slice_lists.get(k, ())), by_pdf, by_doc)}
        for k in ("pilot", "shots")
    }
    both = bases["pilot"] & bases["shots"]
    if both:
        raise SelectError(f"pilot と shots が base を共有している: {sorted(both)}")


def _resolve(ids, by_pdf, by_doc) -> list[PdfRef]:
    out: list[PdfRef] = []
    unknown = []
    for i in ids:
        if i in by_pdf:
            out.append(by_pdf[i])
        elif i in by_doc:
            out.extend(by_doc[i])
        else:
            unknown.append(i)
    if unknown:
        raise SelectError(
            f"未知の ID {len(unknown)} 件: {unknown[:5]}（文書 ID か PDF ID を指定する）"
        )
    return out

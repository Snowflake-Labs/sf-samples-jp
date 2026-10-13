"""テスト用の合成データセット（実データの断片を使わない）。

manifest.json・SHA256SUMS・文書ファイルを一時ディレクトリに作る。中身は架空の文字列で、
PDF としての正しさは要らない（取得と照合の試験に使う）。`SyntheticDoc.pdf_pages` を渡した文書だけは、
架空の条文から作った本物の PDF（fixtures/synthetic_pdf.py）を doc.pdf に置く（読み取りの試験に使う）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

GOLD = ("answer.json", "elements.jsonl", "source.json", "layout.json", "qa.json")


@dataclass
class SyntheticDoc:
    doc_id: str
    content_id: str
    pages: int = 3
    figures: int = 1
    status: str = "ready"
    pdf_pages: list[list[str]] | None = None  # 指定すると doc.pdf を本物の合成 PDF にする


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_dataset(
    root: Path,
    docs: list[SyntheticDoc],
    *,
    dataset_version: str | None = "vtest",
    with_sha256sums: bool = True,
    checksum_files: tuple[str, ...] = (
        "doc.pdf",
        "answer.json",
        "source.json",
        "layout.json",
        "qa.json",
    ),
) -> Path:
    """root に合成データセットを作って root を返す。

    manifest の checksums には checksum_files だけを書き、残り（既定では elements.jsonl）は
    SHA256SUMS にだけ書く（with_sha256sums=False なら期待値の無いファイルになる）。
    """
    root.mkdir(parents=True, exist_ok=True)
    entries, sums = [], []
    for d in docs:
        ddir = root / d.doc_id
        ddir.mkdir(parents=True, exist_ok=True)
        checksums = {}
        for name in ("doc.pdf", *GOLD):
            if name == "doc.pdf" and d.pdf_pages is not None:
                from fixtures.synthetic_pdf import build_pdf

                data = build_pdf(ddir / name, d.pdf_pages).read_bytes()
            else:
                data = f"架空の内容 {d.doc_id} {name}\n".encode()
                (ddir / name).write_bytes(data)
            if name in checksum_files:
                checksums[name] = _sha(data)
            sums.append(f"{_sha(data)}  {d.doc_id}/{name}")
        entries.append(
            {
                "doc_id": d.doc_id,
                "content_id": d.content_id,
                "pages": d.pages,
                "figures": d.figures,
                "status": d.status,
                "checksums": checksums,
            }
        )
    manifest = {"schema_version": "1", "documents": entries}
    if dataset_version:
        manifest["dataset_version"] = dataset_version
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if with_sha256sums:
        (root / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8")
    return root


DEFAULT_DOCS = [
    SyntheticDoc("aaa-0001--style-a", "aaa-0001", pages=4, figures=2),
    SyntheticDoc("aaa-0001--style-b", "aaa-0001", pages=5, figures=2),
    SyntheticDoc("bbb-0001--style-a", "bbb-0001", pages=2, figures=0),
    SyntheticDoc("ccc-0001--style-a", "ccc-0001", pages=9, figures=1, status="failed"),
]

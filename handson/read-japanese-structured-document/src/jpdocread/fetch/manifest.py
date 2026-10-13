"""データセットの索引（manifest.json と SHA256SUMS）の読み込み。

manifest.json は両データセットで共通の形を持つ（`documents[]` に doc_id・content_id・pages・figures・status・checksums）。
約款は `dataset_version` を持つが、契約書は持たない。持たないときは manifest.json の SHA-256 の先頭 12 桁を版とする
（同じ版名で中身が違う manifest を取り違えないため）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST = "manifest.json"
SHA256SUMS = "SHA256SUMS"


class ManifestError(ValueError):
    """manifest.json・SHA256SUMS が読めない・形が違う。"""


# doc_id はディレクトリ名に使うので、英数字・`.`・`_`・`-` に限る（`/` や `..` でデータの外に出さない）
_DOC_ID_RE = re.compile(r"^(?!\.)[A-Za-z0-9._-]+$")


def is_safe_doc_id(doc_id: str) -> bool:
    return bool(_DOC_ID_RE.match(doc_id)) and ".." not in doc_id


@dataclass(frozen=True)
class DocEntry:
    doc_id: str
    content_id: str
    status: str
    pages: int
    figures: int
    checksums: dict[str, str]

    @property
    def ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class Manifest:
    version: str
    documents: dict[str, DocEntry]

    def ready_ids(self) -> list[str]:
        return [d for d, e in self.documents.items() if e.ready]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise ManifestError(f"{MANIFEST} が無い: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        docs = {}
        for d in data["documents"]:
            if not isinstance(d["doc_id"], str) or not is_safe_doc_id(d["doc_id"]):
                raise ManifestError(f"{path}: doc_id に使えない文字がある: {d['doc_id']!r}")
            docs[d["doc_id"]] = DocEntry(
                doc_id=d["doc_id"],
                content_id=d["content_id"],
                status=d["status"],
                pages=int(d["pages"]),
                figures=int(d.get("figures", 0)),
                checksums=dict(d.get("checksums") or {}),
            )
    except ManifestError:
        raise
    except (KeyError, TypeError, ValueError) as e:
        raise ManifestError(f"{path}: manifest の形が想定と違う: {e}") from e
    version = data.get("dataset_version") or f"sha-{sha256_file(path)[:12]}"
    return Manifest(version=str(version), documents=docs)


def load_sha256sums(path: Path) -> dict[str, str]:
    """`<sha256>  <相対パス>` の行を辞書にする。ファイルが無ければ空（約款のデータセットは持たない）。"""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ManifestError(f"{path}:{lineno}: SHA256SUMS の行の形が違う: {line!r}")
        out[parts[1].strip().lstrip("*")] = parts[0].lower()
    return out

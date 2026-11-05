"""取得した PDF の照合（SHA-256）。

照合値は公開索引に入っている（保険約款は索引のファイル一覧の値、契約書は Hub の LFS の値）。
照合値の無いファイルは「照合済み」とみなさず「未照合」として数える。不一致は止める。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import PdfRef

_CHUNK = 1 << 20


class VerifyError(RuntimeError):
    """照合値と一致しないファイルがある。"""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class VerifyReport:
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)
    actual: dict[str, str] = field(default_factory=dict)

    def status(self, pdf_id: str) -> str:
        if pdf_id in self.mismatched:
            return "mismatch"
        return "verified" if pdf_id in self.verified else "unverified"


def verify_pdfs(refs: Iterable[PdfRef], root: Path) -> VerifyReport:
    rep = VerifyReport()
    for r in refs:
        f = root / r.hub_path
        if not f.is_file():
            raise VerifyError(f"取得したはずのファイルが無い: {f}")
        got = sha256_file(f)
        rep.actual[r.pdf_id] = got
        if r.sha256 is None:
            rep.unverified.append(r.pdf_id)
        elif got == r.sha256:
            rep.verified.append(r.pdf_id)
        else:
            rep.mismatched.append(r.pdf_id)
    if rep.mismatched:
        raise VerifyError(
            f"照合値と一致しない PDF {len(rep.mismatched)} 件: {rep.mismatched[:5]}"
            "（ファイルを消して取得し直す。直らなければ revision とデータの場所を確かめる）"
        )
    return rep

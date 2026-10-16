"""取得したファイルの照合。データソースに依らず同じ検査を通す。

期待値は manifest の `checksums` から取り、無ければ SHA256SUMS から取る。
どちらにも無いファイル（約款の elements.jsonl など）は不一致とはせず「未照合」として数えて返す。
黙って照合済みにはしない。不一致・欠落は全件を列挙してから失敗する。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .manifest import Manifest, sha256_file


class VerificationError(RuntimeError):
    """照合に失敗した（不一致・欠落・ready でない）。"""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        head = "\n  - ".join(self.problems[:20])
        more = f"\n  （ほか {len(self.problems) - 20} 件）" if len(self.problems) > 20 else ""
        hint = (
            "\n  取得元が正しいのに一致しないときは、data/ の該当ファイルを削除してから取り直す"
            "（ローカル取得は大きさと更新時刻が同じファイルをコピーし直さない）"
        )
        super().__init__(f"照合に失敗した（{len(self.problems)} 件）:\n  - {head}{more}{hint}")


@dataclass
class VerifyReport:
    verified: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)  # 期待値が無いファイル

    def summary(self) -> dict[str, int]:
        return {"verified": len(self.verified), "unverified": len(self.unverified)}


def expected_sha256(manifest: Manifest, sums: dict[str, str], doc_id: str, file: str) -> str | None:
    entry = manifest.documents.get(doc_id)
    if entry and file in entry.checksums:
        return entry.checksums[file].lower()
    return sums.get(f"{doc_id}/{file}")


def verify_files(
    root: Path,
    manifest: Manifest,
    sums: dict[str, str],
    doc_ids: Sequence[str],
    files: Sequence[str],
) -> VerifyReport:
    report = VerifyReport()
    problems: list[str] = []
    for doc_id in doc_ids:
        entry = manifest.documents.get(doc_id)
        if entry is None:
            problems.append(f"{doc_id}: manifest に無い")
            continue
        if not entry.ready:
            problems.append(f"{doc_id}: status が ready でない（{entry.status}）")
            continue
        for file in files:
            rel = f"{doc_id}/{file}"
            path = root / rel
            if not path.exists():
                problems.append(f"{rel}: ファイルが無い")
                continue
            expected = expected_sha256(manifest, sums, doc_id, file)
            if expected is None:
                report.unverified.append(rel)
            elif sha256_file(path) != expected:
                problems.append(f"{rel}: SHA-256 が一致しない")
            else:
                report.verified.append(rel)
    if problems:
        raise VerificationError(problems)
    return report

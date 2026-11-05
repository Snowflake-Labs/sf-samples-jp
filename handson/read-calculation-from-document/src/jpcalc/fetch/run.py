"""予測用の取得（PDF だけ）と取得記録。

1. 対象の PDF のパスが予測用の allow-list（configs/guard.yaml の predict_allow）に入ることを確かめる。
2. PDF だけを <DATA>/<corpus>/<revision>/files/ に取得する（取得済みで照合が通るものは取り直さない）。
3. 置き場所（files/）の下が、予測用の allow-list に入る PDF だけであることを確かめる（隠しファイルも含む）。
4. 照合値と照合し、PDF のページ数を数え、取得記録（fetch_record.json）に PDF ID ごとに書き足す。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .adapters import AdapterError, PdfRef, check_predict_paths, match_path
from .sources import all_files_under
from .verify import VerifyReport, sha256_file, verify_pdfs

FILES_DIR = "files"
FETCH_RECORD = "fetch_record.json"


def count_pages(path: Path) -> int:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return len(pdf.pages)


def check_files_dir(root: Path, predict_allow: Sequence[str]) -> None:
    """予測側の置き場所に、allow-list の PDF 以外のファイルが無いこと。あれば止める。"""
    bad = []
    for f in all_files_under(root):
        rel = f.relative_to(root).as_posix()
        if f.is_symlink() or not any(match_path(rel, a) for a in predict_allow):
            bad.append(rel)
    if bad:
        raise AdapterError(
            f"予測用の置き場所 {root} に PDF 以外のファイルがある（{len(bad)} 件: {bad[:3]}）。"
            "そのファイルを消してから取得し直す"
        )


def fetch_predict(
    refs: Sequence[PdfRef], source, corpus_root: Path, predict_allow: Sequence[str]
) -> tuple[VerifyReport, dict]:
    check_predict_paths([r.hub_path for r in refs], predict_allow)
    root = corpus_root / FILES_DIR
    todo = [
        r
        for r in refs
        if not (
            (root / r.hub_path).is_file()
            and r.sha256
            and sha256_file(root / r.hub_path) == r.sha256
        )
    ]
    source.fetch_files(root, [r.hub_path for r in todo])
    check_files_dir(root, predict_allow)
    rep = verify_pdfs(refs, root)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = [
        {
            **r.to_dict(),
            "local_path": str((root / r.hub_path).relative_to(corpus_root)),
            "sha256_actual": rep.actual[r.pdf_id],
            "verify": rep.status(r.pdf_id),
            "page_count": count_pages(root / r.hub_path),
            "source": source.label,
            "checked_at": now,
        }
        for r in refs
    ]
    path = corpus_root / FETCH_RECORD
    known = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(
        known.get("pdfs"), dict
    ):  # 無い・形が違う記録は作り直す（PDF の照合はこの回で行った）
        known = {"pdfs": {}}
    known["pdfs"].update({e["pdf_id"]: e for e in entries})
    known["pdfs"] = dict(sorted(known["pdfs"].items()))
    allp = known["pdfs"].values()
    known["n_pdfs"] = len(known["pdfs"])
    known["n_unverified"] = sum(1 for e in allp if e["verify"] != "verified")
    path.write_text(json.dumps(known, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {"n_pdfs": len(refs), "n_downloaded": len(todo), "pdfs": entries}
    return rep, record

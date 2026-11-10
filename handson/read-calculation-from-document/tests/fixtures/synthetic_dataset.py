"""テスト用の合成データセット（両コーパスの固定版と同じ形のツリー。中身は架空）。

予測用の PDF に加えて、正解側のファイル（評価用の正解・読み取りの正解・暦）と、正解由来の列を持つ完全な索引も
置く。予測用の取得がそれらに触れないこと、公開索引に正解由来の列が写らないことを試すため。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .synthetic_pdf import build_pdf, contract_pages, yakkan_pages

# 保険約款：(doc_id, base, genre, styles)
YAKKAN_DOCS = [
    ("auto-0001-c1", "auto-0001", "auto", ["s-a", "s-b"]),
    ("auto-0001-c2", "auto-0001", "auto", ["s-a"]),
    ("auto-0002-c1", "auto-0002", "auto", ["s-b"]),
    ("auto-0003-c1", "auto-0003", "auto", ["s-a"]),
    ("life-0001-c1", "life-0001", "life", ["s-c"]),
    ("life-0002-c1", "life-0002", "life", ["s-c", "s-a"]),
    ("life-0003-c1", "life-0003", "life", ["s-a"]),
]
# 契約書：(content_id, base, doctype, style)
CONTRACT_DOCS = [
    ("con-0101", "con-0001", "nda", "ct-x"),
    ("con-0102", "con-0001", "nda", "ct-y"),
    ("con-0201", "con-0002", "nda", "ct-x"),
    ("con-0301", "con-0003", "lic", "ct-y"),
    ("con-0401", "con-0004", "lic", "ct-x"),
]
GOLD_COLUMNS = ("rules", "cases", "patterns", "challenge")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_yakkan(root: Path) -> Path:
    files: dict[str, str] = {}
    docs = []
    for doc_id, base, genre, styles in YAKKAN_DOCS:
        d = root / "documents" / doc_id
        for st in styles:
            pdf = build_pdf(d / f"{doc_id}--{st}" / "doc.pdf", yakkan_pages())
            files[str(pdf.relative_to(root))] = _sha(pdf)
            (d / f"{doc_id}--{st}" / "layout.json").write_text("{}", encoding="utf-8")
        (d / "policy.json").write_text("{}", encoding="utf-8")
        (d / "calc" / "tests").mkdir(parents=True)
        (d / "calc" / "spec.json").write_text('{"secret": 1}', encoding="utf-8")
        (d / "calc" / "tests" / "test_calc.py").write_text("", encoding="utf-8")
        docs.append(
            {
                "doc_id": doc_id,
                "base_content_id": base,
                "genre": genre,
                "styles": styles,
                "pages": 2,
                "rules": 5,
                "cases": 40,
                "patterns": ["P01"],
                "challenge": None,
            }
        )
    (root / "views").mkdir()
    (root / "views" / "pages.jsonl").write_text("", encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"documents": docs, "files": files, "totals": {"rules": 35}}), encoding="utf-8"
    )
    return root


def build_contract(root: Path) -> tuple[Path, dict[str, str]]:
    """契約書のツリーと、Hub の LFS の SHA-256 に当たる値（パス → SHA-256）を返す。"""
    lfs: dict[str, str] = {}
    lines = []
    for cid, base, doctype, st in CONTRACT_DOCS:
        d = root / "inputs" / cid
        pdf = build_pdf(d / f"{cid}--{st}.pdf", contract_pages())
        rel = str(pdf.relative_to(root))
        lfs[rel] = _sha(pdf)
        for name in ("contract.json", "layout.json", "calendar.json", "tasks.jsonl"):
            (d / name).write_text("{}", encoding="utf-8")
        a = root / "answers" / cid / "tests"
        a.mkdir(parents=True)
        (a.parent / "spec.json").write_text("{}", encoding="utf-8")
        lines.append(
            json.dumps(
                {
                    "content_id": cid,
                    "base_content_id": base,
                    "doctype": doctype,
                    "style_id": st,
                    "pages": 1,
                    "pdf_file": rel,
                    "n_rules": 6,
                    "patterns": ["K01"],
                    "challenge_type": "anomaly",
                }
            )
        )
    (root / "data").mkdir()
    (root / "data" / "documents.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "data" / "rules.jsonl").write_text("", encoding="utf-8")
    return root, lfs

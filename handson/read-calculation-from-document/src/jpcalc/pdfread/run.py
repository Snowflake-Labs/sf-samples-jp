"""pdoc を作る入口。取得の記録で照合済みの PDF だけを読み、pdoc を生成物の置き場所に書く。

読む PDF は取得の記録（fetch_record.json）に照合済みとして載っているものだけで、読む直前に SHA-256 を
計算し直して記録と照合する（記録の後に差し替えられた PDF を読まない）。予測側のモジュールである。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..fetch.run import FETCH_RECORD
from ..fetch.verify import sha256_file
from .pdoc import build


class PdocError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdocResult:
    pdf_id: str
    path: Path
    n_articles: int
    n_read_errors: int
    n_value_span_errors: int


def load_record(corpus_root: Path) -> dict[str, dict]:
    path = corpus_root / FETCH_RECORD
    if not path.is_file():
        raise PdocError(f"取得の記録がありません: {path}（先に jpcalc fetch を実行してください）")
    rec = json.loads(path.read_text(encoding="utf-8"))
    pdfs = rec.get("pdfs")
    if not isinstance(pdfs, dict):
        raise PdocError(f"取得の記録の形が違います: {path}（jpcalc fetch で作り直してください）")
    return pdfs


def make_pdocs(corpus_root: Path, pdf_ids: Sequence[str], out_dir: Path) -> list[PdocResult]:
    """pdf_ids の pdoc を作って out_dir/<pdf_id>.json に書く。照合済みでない PDF があれば何も作らずに止まる。"""
    record = load_record(corpus_root)
    missing = [p for p in pdf_ids if p not in record]
    if missing:
        raise PdocError(
            f"取得の記録に無い PDF: {', '.join(missing)}（先に jpcalc fetch で取得してください）"
        )
    bad = [p for p in pdf_ids if record[p].get("verify") != "verified"]
    if bad:
        raise PdocError(f"照合済みでない PDF: {', '.join(bad)}（照合できない PDF は読まない）")
    paths: dict[str, Path] = {}
    for pid in pdf_ids:
        e = record[pid]
        path = corpus_root / e["local_path"]
        if not path.is_file() or sha256_file(path) != e["sha256_actual"]:
            raise PdocError(
                f"PDF が取得の記録と一致しません: {pid}（jpcalc fetch で取り直してください）"
            )
        paths[pid] = path
    # すべての pdoc をメモリ上で作ってから書く（途中で失敗したら何も書かない）
    docs = {pid: build(pid, paths[pid]) for pid in pdf_ids}
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for pid, doc in docs.items():
        dst = out_dir / f"{pid}.json"
        dst.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        p = doc["pdoc"]
        results.append(
            PdocResult(
                pid,
                dst,
                p["stats"].get("head_article", 0),
                len(p["read_errors"]),
                len(p["value_span_errors"]),
            )
        )
    return results

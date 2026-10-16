"""正解データの読み込みと整合性検査（採点側専用）。

gold（正解）の読み込みと checksum 照合。**eval 側のみ**（§1.2）。

`read/` からこのモジュールを import してはならない。`jpdocread guard` が検査する。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..common.paths import DOCS, MANIFEST, doc_dir


class ChecksumMismatch(RuntimeError):
    """manifest の SHA-256 と実ファイルが一致しない（§1.1：採点を中断する）。"""


@dataclass(frozen=True)
class GoldPage:
    number: int
    text: str
    text_with_furniture: str


@dataclass(frozen=True)
class GoldDoc:
    doc_id: str
    pages: list[GoldPage]
    outline: list[dict]

    def page(self, number: int) -> GoldPage:
        for p in self.pages:
            if p.number == number:
                return p
        raise KeyError(f"{self.doc_id}: page {number} not in gold")


@lru_cache(maxsize=1)
def _eval_db() -> str:
    from ..common.names import load_names

    return load_names().eval_db


def manifest_checksums() -> dict[str, dict[str, str]]:
    """manifest.json の `documents[].checksums` を doc_id で引く。"""
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {d["doc_id"]: d["checksums"] for d in m["documents"]}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksums(doc_ids: list[str]) -> dict[str, dict[str, bool]]:
    """manifest の checksums と実ファイルを照合する。

    戻り値: {doc_id: {filename: ok}}。1 つでも False があれば呼び出し側が中断すること。
    """
    mf = manifest_checksums()
    result: dict[str, dict[str, bool]] = {}
    for doc_id in doc_ids:
        per_file: dict[str, bool] = {}
        for fname, expected in mf[doc_id].items():
            path = doc_dir(doc_id) / fname
            per_file[fname] = path.exists() and sha256_file(path) == expected
        result[doc_id] = per_file
    return result


GOLD_JSON_FILES = ("source.json", "layout.json", "answer.json", "qa.json")


def pdf_corresponds_to_layout(doc_id: str) -> tuple[bool, dict]:
    """`doc.pdf` が `layout.json` と**内容として**対応しているかを検査する。

    S0 の実測：manifest の `doc.pdf` の SHA-256 は**全文書で不一致**である
    （PDF が manifest 生成後に再レンダリングされた。JSON 側は全て一致）。
    バイト一致は失われているが、ページ数・ページ寸法・1 ページ目の先頭行の存在は
    一致する。そこで**バイト検査を内容対応検査に置き換え、その事実を記録する**。
    黙って無視はしない。
    """
    import pdfplumber  # 遅延 import（採点以外で pdfplumber を要求しない）

    lay = load_layout(doc_id)
    ev: dict = {"doc_id": doc_id}
    try:
        with pdfplumber.open(doc_dir(doc_id) / "doc.pdf") as pdf:
            ev["pdf_pages"] = len(pdf.pages)
            ev["layout_pages"] = lay["page_count"]
            p0 = pdf.pages[0]
            ev["pdf_size"] = [round(float(p0.width), 2), round(float(p0.height), 2)]
            ev["layout_size"] = [round(v, 2) for v in lay["page_size_pt"]]
            tl = lay["pages"][0].get("text_lines") or []
            first = "".join((tl[0]["text"] if tl else "").split())
            joined = "".join(w["text"] for w in p0.extract_words())
            ev["first_line_found"] = bool(first) and first in joined
    except Exception as e:  # noqa: BLE001
        ev["error"] = str(e)
        return False, ev

    ok = (
        ev["pdf_pages"] == ev["layout_pages"]
        and abs(ev["pdf_size"][0] - ev["layout_size"][0]) < 0.6
        and abs(ev["pdf_size"][1] - ev["layout_size"][1]) < 0.6
        and ev["first_line_found"]
    )
    ev["ok"] = ok
    return ok, ev


def assert_checksums(doc_ids: list[str]) -> dict:
    """gold の整合性を検査する。

    - **gold JSON（source/layout/answer/qa）の不一致は即中断**（答案が改変されている）。
    - `doc.pdf` の不一致は**内容対応検査に置き換え**、結果を戻り値で報告する。
      対応検査も落ちたら中断する。
    """
    res = verify_checksums(doc_ids)
    json_bad = {
        d: [f for f in GOLD_JSON_FILES if f in files and not files[f]] for d, files in res.items()
    }
    json_bad = {d: fs for d, fs in json_bad.items() if fs}
    if json_bad:
        raise ChecksumMismatch(f"gold JSON の checksum 不一致（採点中断）: {json_bad}")

    pdf_mismatch = [d for d, files in res.items() if not files.get("doc.pdf", True)]
    # 評価側の GOLD ステージには doc.pdf を置かない（予測側の入力と分ける）。doc.pdf の整合は
    # 取得時に manifest で照合済み（fetch/verify.py）なので、
    # 手元に doc.pdf が無いときは検査を省き、その事実を戻り値に残す（黙って合格にしない）。
    absent = [d for d in pdf_mismatch if not (doc_dir(d) / "doc.pdf").exists()]
    evidence = []
    failed = []
    for d in pdf_mismatch:
        if d in absent:
            continue
        ok, ev = pdf_corresponds_to_layout(d)
        evidence.append(ev)
        if not ok:
            failed.append(d)
    if failed:
        raise ChecksumMismatch(f"doc.pdf が checksum も内容対応も満たさない（採点中断）: {failed}")
    return {
        "gold_json_checksum_ok": len(res),
        "pdf_checksum_mismatch": sorted(set(pdf_mismatch) - set(absent)),
        "pdf_content_correspondence_ok": len(pdf_mismatch) - len(failed) - len(absent),
        "pdf_not_in_gold_stage": len(absent),
        "pdf_check": f"setup 時に照合（{_eval_db()}.GOLD.MANIFEST）" if absent else "採点時に照合",
        "evidence": evidence,
    }


@lru_cache(maxsize=64)
def load_gold(doc_id: str) -> GoldDoc:
    with (doc_dir(doc_id) / "answer.json").open(encoding="utf-8") as f:
        a = json.load(f)
    pages = [
        GoldPage(
            number=p["number"],
            text=p["text"],
            text_with_furniture=p.get("text_with_furniture", p["text"]),
        )
        for p in a["pages"]
    ]
    return GoldDoc(doc_id=doc_id, pages=pages, outline=a.get("outline", []))


@lru_cache(maxsize=64)
def load_elements(doc_id: str) -> list[dict]:
    out = []
    with (doc_dir(doc_id) / "elements.jsonl").open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


@lru_cache(maxsize=64)
def load_source(doc_id: str) -> dict:
    with (doc_dir(doc_id) / "source.json").open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=64)
def load_layout(doc_id: str) -> dict:
    with (doc_dir(doc_id) / "layout.json").open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=64)
def load_qa(doc_id: str) -> list[dict]:
    with (doc_dir(doc_id) / "qa.json").open(encoding="utf-8") as f:
        return json.load(f)["items"]


def gold_exists(doc_id: str) -> bool:
    return (DOCS / doc_id / "answer.json").exists()

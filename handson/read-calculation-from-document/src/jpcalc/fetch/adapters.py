"""コーパスの違いを吸収する adapter（予測側）。

予測側が読むのは公開索引（public_index.jsonl）だけである。公開索引は文書ごとに 1 行で、
正解に由来しない列（文書 ID・base・層・体裁・ページ数）と、PDF ごとのパスと照合値だけを持つ。
公開索引は評価側（jpcalc.eval.catalog）が作る。ここでは読み、PDF 単位の共通形式 PdfRef に写す。
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

PUBLIC_INDEX = "public_index.jsonl"
# 公開索引に置いてよい列（これ以外の列があれば、正解由来の列が混ざったとみなして止まる）
PUBLIC_DOC_KEYS = frozenset(
    {"corpus", "doc_id", "split_group", "stratum", "styles", "pages", "pdfs"}
)
PUBLIC_PDF_KEYS = frozenset({"style", "pdf_id", "hub_path", "sha256"})


# 文書 ID・体裁名に使ってよい文字（取得のパターンでワイルドカードとして解釈される文字を入れない）
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class AdapterError(ValueError):
    """公開索引が不正、またはパスが allow-list から外れる。"""


@dataclass(frozen=True)
class PdfRef:
    corpus: str
    doc_id: str
    pdf_id: str
    split_group: str
    stratum: str
    style: str
    pages_index: (
        int  # 索引のページ数（保険約款は文書単位の値。体裁ごとの正確な値は PDF から数える）
    )
    hub_path: str
    sha256: str | None  # 照合値。None は「照合値が無い（未照合）」

    def to_dict(self) -> dict:
        return asdict(self)


def render(template: str, **values: str) -> str:
    """paths のひな型（{doc_id}・{style}）に値を入れる。未知の置換名はエラー。"""
    try:
        return template.format(**values)
    except KeyError as e:
        raise AdapterError(f"ひな型 {template!r} の置換名 {e} に値が無い") from e


def match_path(path: str, pattern: str) -> bool:
    """`/` で区切った各部分を fnmatch で照合する（`*` が `/` をまたがない）。"""
    a, b = path.split("/"), pattern.split("/")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(x, y) for x, y in zip(a, b, strict=True))


def check_predict_paths(paths: Iterable[str], allow: Sequence[str]) -> None:
    """予測用の取得パスが allow-list（PDF だけ）に入ることを確かめる。外れたら止まる。"""
    bad = [p for p in paths if not p.endswith(".pdf") or not any(match_path(p, a) for a in allow)]
    if bad:
        raise AdapterError(f"予測用の allow-list から外れるパス {len(bad)} 件: {bad[:5]}")


def read_public_index(path: Path) -> list[dict]:
    if not path.is_file():
        raise AdapterError(
            f"公開索引が無い: {path}（先に `jpcalc index --corpus <名前>` を実行する）"
        )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for r in rows:
        extra = set(r) - PUBLIC_DOC_KEYS
        if extra:
            raise AdapterError(
                f"公開索引に許されない列がある: {sorted(extra)}（{r.get('doc_id')}）"
            )
        for p in r["pdfs"]:
            extra = set(p) - PUBLIC_PDF_KEYS
            if extra:
                raise AdapterError(f"公開索引の PDF に許されない列がある: {sorted(extra)}")
    return rows


def pdf_refs(rows: Iterable[dict], cfg) -> list[PdfRef]:
    """公開索引の行を PDF 単位の PdfRef に写す。パスはコーパス設定のひな型と一致しなければ止まる。"""
    out: list[PdfRef] = []
    for r in rows:
        if r["corpus"] != cfg.name:
            raise AdapterError(f"公開索引のコーパスが違う: {r['corpus']}（期待 {cfg.name}）")
        for p in r["pdfs"]:
            for v in (r["doc_id"], p["style"]):
                if not _ID_RE.match(v):
                    raise AdapterError(f"文書 ID・体裁名に使えない文字がある: {v!r}")
            want = render(cfg.paths.pdf, doc_id=r["doc_id"], style=p["style"])
            pid = render(cfg.paths.pdf_id, doc_id=r["doc_id"], style=p["style"])
            if p["hub_path"] != want or p["pdf_id"] != pid:
                raise AdapterError(
                    f"{r['doc_id']}: PDF のパスがひな型と違う（{p['hub_path']} ≠ {want}）。推測で補わない"
                )
            out.append(
                PdfRef(
                    corpus=cfg.name,
                    doc_id=r["doc_id"],
                    pdf_id=pid,
                    split_group=r["split_group"],
                    stratum=r["stratum"],
                    style=p["style"],
                    pages_index=int(r["pages"]),
                    hub_path=want,
                    sha256=p["sha256"],
                )
            )
    ids = [x.pdf_id for x in out]
    if len(set(ids)) != len(ids):
        raise AdapterError("PDF ID が重複している")
    return out

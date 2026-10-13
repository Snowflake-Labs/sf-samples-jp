"""R2（LAYOUT）— `AI_PARSE_DOCUMENT` の応答を読む。

変更点：`AI_PARSE_DOCUMENT` の呼び出しは S20（SQL プロシージャ）に移した。S50 は S20 の結果テーブルを
`write_cache()` で親と同じキャッシュ形式に書き出し、ここでは**キャッシュだけ**を読む
（キャッシュが無ければ CacheMissError。空文字で埋めない）。キャッシュキーの作り方は親と同じ。

**必須事項：**
- `return_error_details => TRUE` を常に渡す（素の NULL は記録されない失敗）
- `page_filter` は **0 始まり・end 排他**。反復中は常に使う（§1.5）
- 応答は `(doc_id, reader, options_hash)` でキャッシュして再呼出しを避ける
- `page_split` は段落と表をページ境界で切断する。下流で再結合が必要

**予測側モジュール。** gold を開かない。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ...common.paths import WORK

CACHE = WORK / "parse"


@dataclass
class ParseResult:
    doc_id: str
    reader: str
    options: dict
    options_hash: str
    pages: dict[int, str] = field(default_factory=dict)  # 1-based ページ番号 → 本文
    err: str | None = None
    page_count: int | None = None
    query_id: str | None = None
    wall_clock_s: float = 0.0
    raw: dict | None = None
    from_cache: bool = False
    requested_pages: tuple[int, ...] = ()

    @property
    def n_null_pages(self) -> int:
        return sum(1 for v in self.pages.values() if not v)

    @property
    def n_missing_pages(self) -> int:
        return sum(1 for page in self.requested_pages if page not in self.pages)


class CacheMissError(FileNotFoundError):
    """The requested parse is not cached and remote execution was disabled."""


def _requested_pages(
    page_filter: list[tuple[int, int]] | None,
    page_count: int | None = None,
) -> tuple[int, ...]:
    if page_filter:
        return tuple(page for start, end in page_filter for page in range(start + 1, end + 1))
    if page_count is not None:
        return tuple(range(1, page_count + 1))
    return ()


def options_hash(options: dict) -> str:
    return hashlib.sha256(
        json.dumps(options, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def cache_path(doc_id: str, reader: str, oh: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{doc_id}__{reader}__{oh}.json"


MODE_BY_READER = {"R1": "OCR", "R2": "LAYOUT"}


def parse_doc(
    doc_id: str,
    reader: str = "R1",
    page_filter: list[tuple[int, int]] | None = None,
    page_split: bool = True,
    use_cache: bool = True,
    cache_only: bool = False,
) -> ParseResult:
    """`AI_PARSE_DOCUMENT` を 1 文書（または指定ページ範囲）に適用する。

    page_filter: [(start, end)] の **0 始まり・end 排他**。None なら全ページ。
    入力は `doc.pdf` だけ（移植元の `from_png` 分岐は存在しないファイルを指していたので削除した。D-019）。
    """
    mode = MODE_BY_READER[reader]
    requested = _requested_pages(page_filter)
    options: dict = {"mode": mode}
    is_image = False  # キャッシュキーの形を親と揃えるため残す
    if page_filter:
        options["page_filter"] = [{"start": s, "end": e} for s, e in page_filter]
    elif page_split:
        options["page_split"] = True

    target = f"{doc_id}/doc.pdf"
    # **キャッシュキーは「読む範囲」で正規化する（W3 C で 135 ページを二重課金して学んだ）。**
    # `page_filter=[(0, N)]`（全ページを明示）と `page_filter=None`（既定で全ページ）は
    # **結果が同一なのにハッシュが違う**ため、S2 で全文を読んだ 10 文書を
    # ALL の実行で再度課金した（`{'mode':'LAYOUT','page_filter':[{0,16}]}` 対
    # `{'mode':'LAYOUT','page_split':True}`）。
    #
    # 正規化は「全ページを指す指定は `None` と同じ鍵にする」だけでよい。
    # ページ数はローカル幾何（`doc.pdf` 由来なので予測側で使って構わない）から採る。
    key_pages: list[int] | None = sorted(requested) if requested else None
    if key_pages is not None and not is_image:
        try:
            from ..geometry import read_pages

            n_local = len(read_pages(doc_id))
            if n_local and key_pages == list(range(1, n_local + 1)):
                key_pages = None  # 全ページ指定 ＝ 無指定
        except Exception:  # noqa: BLE001 — 幾何が無ければ正規化しないだけ（安全側）
            pass
    oh = options_hash({"mode": mode, "target": target, "pages": key_pages, "image": is_image})
    cp = cache_path(doc_id, reader, oh)
    if use_cache and cp.exists():
        d = json.loads(cp.read_text(encoding="utf-8"))
        cached_pages = {int(k): v for k, v in d.get("pages", {}).items()}
        requested = _requested_pages(page_filter, d.get("page_count"))
        return ParseResult(
            doc_id=doc_id,
            reader=reader,
            options=options,
            options_hash=oh,
            pages=cached_pages,
            err=d.get("err"),
            page_count=d.get("page_count"),
            query_id=d.get("query_id"),
            wall_clock_s=d.get("wall_clock_s", 0.0),
            raw=d.get("raw"),
            from_cache=True,
            requested_pages=requested,
        )
    raise CacheMissError(
        f"parse cache miss: {doc_id} {reader} {oh}（S20 の結果が書き出されていない）"
    )


def full_doc_key(doc_id: str) -> str:
    """文書全体を LAYOUT で読んだ応答のキャッシュキー（`parse_doc(doc_id, "R2")` と同じ鍵）。"""
    return options_hash(
        {"mode": "LAYOUT", "target": f"{doc_id}/doc.pdf", "pages": None, "image": False}
    )


def write_cache(
    doc_id: str,
    pages: dict[int, str],
    err: str | None,
    page_count: int | None,
    query_id: str | None,
) -> str:
    """S20 の結果 1 文書ぶんを親と同じ形式でキャッシュに書く。"""
    cp = cache_path(doc_id, "R2", full_doc_key(doc_id))
    cp.write_text(
        json.dumps(
            {
                "pages": {str(k): v for k, v in sorted(pages.items())},
                "err": err,
                "page_count": page_count,
                "query_id": query_id,
                "wall_clock_s": 0.0,
                "options": {"mode": "LAYOUT", "page_split": True},
                "target": f"{doc_id}/doc.pdf",
                "raw": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return str(cp)

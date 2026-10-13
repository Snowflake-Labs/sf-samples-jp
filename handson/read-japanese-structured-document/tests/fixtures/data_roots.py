"""移植したテストが使う実データの置き場所。

1. `DATA_ROOT_YAKKAN`・`DATA_ROOT_CONTRACT`（環境変数か git 管理外の configs/deploy.local.env。手元のデータセット全体）
2. 無ければ、Hugging Face から取得済みの `data/<corpus>/<版>-hf-<rev>/`（`jpdocread fetch --eval` で取ったもの）
どちらも無ければ None で、それを使うテストは `SKIP_REASON` を付けてスキップする（データセットはリポジトリに含めない）。
2 は取得した文書しか持たないので、文書が無いテストは文書ごとにスキップする（tests/ported/conftest.py）。
"""

from __future__ import annotations

from pathlib import Path

from jpdocread.common.local_settings import lookup_local
from jpdocread.common.paths import DATA_DIR
from jpdocread.fetch.manifest import MANIFEST


def _fetched(corpus: str) -> Path | None:
    """取得済みの HF 由来のデータのうち、文書の多いもの。"""
    cands = [p for p in (DATA_DIR / corpus).glob("*-hf-*") if (p / MANIFEST).exists()]
    return max(cands, key=lambda p: sum(1 for c in p.iterdir() if c.is_dir()), default=None)


def _root(key: str, corpus: str) -> Path | None:
    v = lookup_local(key)
    if v and Path(v).is_dir():
        return Path(v)
    return _fetched(corpus)


YDOCS = _root("DATA_ROOT_YAKKAN", "yakkan")
CDOCS = _root("DATA_ROOT_CONTRACT", "contract")
SKIP_REASON = (
    "実データが無い（`uv run jpdocread fetch --corpus <c> --docs-file tests/fixtures/real_docs_<c>.txt --eval` で"
    "Hugging Face から取得するか、DATA_ROOT_YAKKAN・DATA_ROOT_CONTRACT を設定すると走る。"
    "データセットはリポジトリに含めない）"
)

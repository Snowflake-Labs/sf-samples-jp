"""移植したテスト（tests/ported/）の共通の準備。

移植元のテストの一部は実文書（約款の docs・契約書の docs_contracts）を読む。本リポジトリはデータを持たないので、
置き場所を configs/deploy.local.env（git 管理外）の `DATA_ROOT_YAKKAN`・`DATA_ROOT_CONTRACT`
（または同名の環境変数）から読む。無いときは、実文書を使うテストを理由付きでスキップする。
doc_id の版面（`--ct-`）で約款と契約書を見分けるのは移植元と同じ。正解ファイルは予測側のパスから読まない。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from fixtures.data_roots import CDOCS as _CONTRACT
from fixtures.data_roots import SKIP_REASON
from fixtures.data_roots import YDOCS as _YAKKAN

from jpdocread.common import paths
from jpdocread.read import geometry


def _root_for(doc_id: str) -> Path:
    root = _CONTRACT if "--ct-" in doc_id else _YAKKAN
    if root is None:
        pytest.skip(SKIP_REASON)
    return root


def _doc_pdf(doc_id: str) -> Path:
    return _root_for(doc_id) / doc_id / "doc.pdf"


_orig_geom_paths = geometry.geom_paths


def _geom_paths_lazy(doc_id: str):
    """幾何が無ければ doc.pdf から作ってからパスを返す（移植元と同じ）。"""
    lp, pp = _orig_geom_paths(doc_id)
    if not lp.exists() and _doc_pdf(doc_id).exists():
        lines, pages = geometry.extract_geometry(doc_id)
        with lp.open("w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(asdict(ln), ensure_ascii=False) + "\n")
        with pp.open("w", encoding="utf-8") as f:
            for pg in pages:
                f.write(json.dumps(asdict(pg), ensure_ascii=False) + "\n")
    return lp, pp


def _doc_dir(doc_id: str) -> Path:
    return _root_for(doc_id) / doc_id


paths.doc_pdf = _doc_pdf
geometry.doc_pdf = _doc_pdf
geometry.geom_paths = _geom_paths_lazy

# 採点側の正解の読み込み（eval/gold.py）も文書の系統で置き場所を分ける。テスト用の差し替えで、
# 予測側（read/）のパスには入れない（read/ が正解を開かないことは AST ガードが検査している）
from jpdocread.eval import gold  # noqa: E402

gold.doc_dir = _doc_dir

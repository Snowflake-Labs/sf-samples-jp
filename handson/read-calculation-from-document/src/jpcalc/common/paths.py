"""パスの解決。

ルートは環境変数で差し替えられる（SPCS ジョブではジョブ仕様がマウント先を渡す）。
  JPCALC_HOME      コードと設定のルート（configs/ を持つ）。既定はこのリポジトリのディレクトリ
  JPCALC_DATA_DIR  取得したデータの置き場所。既定は <HOME>/data（git 管理外）
  JPCALC_EVAL_DIR  評価用の正解の置き場所。既定は <HOME>/eval_data（git 管理外。予測用の DATA_DIR の外に置く）
  JPCALC_WORK      中間生成物。既定は <HOME>/work（git 管理外）
  JPCALC_OUT       生成物（pdoc・カード・仕様・Python・自己テスト）。既定は <HOME>/out（git 管理外）
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("JPCALC_HOME") or Path(__file__).resolve().parents[3])
CONFIGS = HOME / "configs"
CORPORA = CONFIGS / "corpora"
SRC = HOME / "src" / "jpcalc"
DATA_DIR = Path(os.environ.get("JPCALC_DATA_DIR") or (HOME / "data"))
EVAL_DATA_DIR = Path(os.environ.get("JPCALC_EVAL_DIR") or (HOME / "eval_data"))
WORK = Path(os.environ.get("JPCALC_WORK") or (HOME / "work"))
OUT = Path(os.environ.get("JPCALC_OUT") or (HOME / "out"))

DEPLOY_ENV = CONFIGS / "deploy.env"
DEPLOY_LOCAL_ENV = CONFIGS / "deploy.local.env"
PIPELINE_YAML = CONFIGS / "pipeline.yaml"
CONVENTIONS_YAML = CONFIGS / "conventions.yaml"
GUARD_YAML = CONFIGS / "guard.yaml"


def corpus_dir(corpus: str, revision: str, data_dir: Path | None = None) -> Path:
    """取得したデータの置き場所：<DATA_DIR>/<corpus>/<revision>/（git 管理外）。"""
    return (data_dir or DATA_DIR) / corpus / revision


def eval_corpus_dir(
    corpus: str, revision: str, eval_dir: Path | None = None, data_dir: Path | None = None
) -> Path:
    """評価用の正解の置き場所：<EVAL_DATA_DIR>/<corpus>/<revision>/。予測用の置き場所の中には置かない。"""
    root = (eval_dir or EVAL_DATA_DIR).resolve()
    pred = (data_dir or DATA_DIR).resolve()
    if root == pred or root.is_relative_to(pred) or pred.is_relative_to(root):
        raise ValueError(f"評価用の置き場所 {root} と予測用の置き場所 {pred} が重なっている")
    return root / corpus / revision

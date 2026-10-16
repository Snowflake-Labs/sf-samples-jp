"""パスの解決。

ルートは環境変数で差し替えられる（SPCS ジョブではジョブ仕様がマウント先を渡す）。移植した read/・eval/ は
import 時にここを読むので、変えるときは import の前に環境変数を設定する（`jpdocread.runtime.configure`）。
  JPDOCREAD_HOME      コードと設定のルート（configs/ を持つ）。既定はこのリポジトリのディレクトリ
  JPDOCREAD_DATA_DIR  取得したデータの置き場所。既定は <HOME>/data（git 管理外）
  JPDOCREAD_DOCS      読み取りの入力（<doc_id>/doc.pdf）と、採点時の正解（<doc_id>/*.json・manifest.json）のルート
  JPDOCREAD_WORK      中間生成物（幾何・領域・クロップ・AI 応答のキャッシュの書き出し）。既定は <HOME>/work
  JPDOCREAD_OUT       読み取り結果 JSON（<doc_id>.json）。既定は <HOME>/out
  JPDOCREAD_SHOTS     図の few-shot 期待 JSON（figure__<doc_id>.json）。既定は configs/shots（その下にコーパス別のディレクトリ）
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = Path(os.environ.get("JPDOCREAD_HOME") or Path(__file__).resolve().parents[3])
CONFIGS = HOME / "configs"
CORPORA = CONFIGS / "corpora"
DATA_DIR = Path(os.environ.get("JPDOCREAD_DATA_DIR") or (HOME / "data"))

DOCS = Path(os.environ.get("JPDOCREAD_DOCS") or DATA_DIR)
MANIFEST = DOCS / "manifest.json"
WORK = Path(os.environ.get("JPDOCREAD_WORK") or (HOME / "work"))
OUT = Path(os.environ.get("JPDOCREAD_OUT") or (HOME / "out"))
SHOTS = Path(os.environ.get("JPDOCREAD_SHOTS") or (CONFIGS / "shots"))

DEPLOY_ENV = CONFIGS / "deploy.env"
DEPLOY_LOCAL_ENV = CONFIGS / "deploy.local.env"
PIPELINE_YAML = CONFIGS / "pipeline.yaml"

# 予測側が文書ディレクトリで開いてよいファイル
PREDICT_FILES: tuple[str, ...] = ("doc.pdf",)

# 評価にだけ使う正解ファイル（--eval のときだけ取得する）
# qa.json は採点に使わないが、移植した採点の整合検査（eval/gold.assert_checksums）が manifest の正解 JSON 4 種の
# 照合を求めるので取得する（移植元も GOLD ステージに置いていた）
GOLD_FILES: tuple[str, ...] = (
    "answer.json",
    "elements.jsonl",
    "source.json",
    "layout.json",
    "qa.json",
)

# 予測側（read/）のコードが参照してはならない名前（正解ファイルと、ページ画像のディレクトリ）
FORBIDDEN_GOLD_FILES: tuple[str, ...] = (
    *GOLD_FILES,
    "passages.jsonl",
    "qrels.jsonl",
    "queries.jsonl",
    "manifest.json",
)
FORBIDDEN_DOC_PATHS: tuple[str, ...] = ("pages/",)


def doc_dir(doc_id: str) -> Path:
    return DOCS / doc_id


def doc_pdf(doc_id: str) -> Path:
    return DOCS / doc_id / "doc.pdf"

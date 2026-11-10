"""手本（few-shot）の読み込み（予測側）。

手本は評価側が DEV の文書（pilot と元文書を共有しない文書）の正解から機械的に作り、work/shots/ に置く
（git 管理外。予測側は作られた手本のファイルだけを読み、正解を開かない）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common.paths import WORK

SHOTS_DIR = WORK / "shots"


class ShotsMissing(FileNotFoundError):
    pass


def shots_path(corpus: str, stage: str, shots_dir: Path | None = None) -> Path:
    """stage は k_cards か d_spec。"""
    return (shots_dir or SHOTS_DIR) / corpus / f"{stage}.json"


def load(corpus: str, stage: str, shots_dir: Path | None = None) -> list[dict]:
    p = shots_path(corpus, stage, shots_dir)
    if not p.is_file():
        raise ShotsMissing(
            f"手本がありません: {p}（評価側の jpcalc make-shots --corpus {corpus} で作るか、"
            "手本なしで試すときは --no-shots を付ける）"
        )
    return json.loads(p.read_text(encoding="utf-8"))

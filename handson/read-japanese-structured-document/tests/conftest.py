from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# 移植した read/・eval/ は import 時にパスを決める（common/paths.py）。テストの書き出しがリポジトリの
# work/・out/ に出ないよう、jpdocread を import する前に一時ディレクトリを指す
_TMP = Path(tempfile.mkdtemp(prefix="jpdocread-test-"))
os.environ.setdefault("JPDOCREAD_WORK", str(_TMP / "work"))
os.environ.setdefault("JPDOCREAD_OUT", str(_TMP / "out"))

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.configs import make_corpus_cfg, make_pipeline_cfg  # noqa: E402
from fixtures.synthetic_dataset import DEFAULT_DOCS, build_dataset  # noqa: E402


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    """合成データセット（ready 3 文書・failed 1 文書）。"""
    return build_dataset(tmp_path / "src", DEFAULT_DOCS)


@pytest.fixture
def pipeline_cfg():
    return make_pipeline_cfg()


@pytest.fixture
def corpus_cfg():
    return make_corpus_cfg()

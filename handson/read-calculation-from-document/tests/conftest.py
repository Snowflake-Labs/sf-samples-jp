from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# テストの書き出しがリポジトリの work/・out/ に出ないよう、jpcalc を import する前に一時ディレクトリを指す
_TMP = Path(tempfile.mkdtemp(prefix="jpcalc-test-"))
os.environ.setdefault("JPCALC_WORK", str(_TMP / "work"))
os.environ.setdefault("JPCALC_OUT", str(_TMP / "out"))

sys.path.insert(0, str(Path(__file__).parent))

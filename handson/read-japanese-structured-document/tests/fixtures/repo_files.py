"""git の管理対象になり得るファイル（追跡済み＋無視されていない未追跡）の一覧。

公開リポジトリの検査（秘密情報・命名）は、.gitignore で除外されるファイル
（deploy.local.env・data/・TASK.md など）を対象にしない。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from jpdocread.common.paths import HOME


def publishable_files(root: Path = HOME) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(root / line for line in out.splitlines() if line and (root / line).is_file())

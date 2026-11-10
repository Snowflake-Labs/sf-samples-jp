"""Hugging Face Hub の偽物（ローカルのツリーを Hub に見立てる）。呼ばれた操作を記録する。"""

from __future__ import annotations

import shutil
from fnmatch import fnmatchcase
from pathlib import Path


class FakeHub:
    def __init__(self, root: Path, lfs: dict[str, str] | None = None) -> None:
        self.root = root
        self.lfs = lfs or {}
        self.gets: list[str] = []
        self.snapshots: list[list[str]] = []

    def get(self, repo_id, revision, path):
        self.gets.append(path)
        return (self.root / path).read_bytes()

    def snapshot(self, repo_id, revision, allow_patterns, local_dir):
        self.snapshots.append(list(allow_patterns))
        # 本物の snapshot_download と同じく、local_dir にリポジトリ全体のファイル一覧を書く
        meta = local_dir / ".cache" / "huggingface" / "trees"
        meta.mkdir(parents=True, exist_ok=True)
        tree = [str(f.relative_to(self.root)) for f in self.root.rglob("*") if f.is_file()]
        (meta / f"{revision}.json").write_text("\n".join(tree), encoding="utf-8")
        for f in self.root.rglob("*"):
            rel = str(f.relative_to(self.root))
            if f.is_file() and any(fnmatchcase(rel, p) for p in allow_patterns):
                (local_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, local_dir / rel)

    def paths_info(self, repo_id, revision, paths):
        return {p: self.lfs[p] for p in paths if p in self.lfs}

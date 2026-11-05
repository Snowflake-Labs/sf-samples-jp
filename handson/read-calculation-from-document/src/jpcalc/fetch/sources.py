"""データの取得元（Hugging Face の固定 revision と、開発用のローカルの写し）。

取得元は 3 つの操作だけを持つ：
- `read_bytes(path)`：1 ファイルをメモリに読む（索引の読み取り用。ディスクに残さない）
- `fetch_files(dest, paths)`：指定したパスだけを dest/<path> に取得する
- `lfs_sha256(paths)`：取得元が知っている SHA-256（Hub の LFS の値）。知らなければ空

どのファイルを取得してよいかは呼び出し側（予測用・評価用の allow-list）が決める。取得元は資格情報を要求しない。
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_PATHS_INFO_BATCH = 50


class SourceError(RuntimeError):
    """取得元の設定が不正、または取得に失敗した。"""


class DataSource(Protocol):
    label: str

    def read_bytes(self, path: str) -> bytes: ...

    def fetch_files(self, dest: Path, paths: Sequence[str]) -> list[Path]: ...

    def lfs_sha256(self, paths: Sequence[str]) -> dict[str, str]: ...

    def fetch_patterns(self, dest: Path, patterns: Sequence[str]) -> list[Path]: ...


class HubClient(Protocol):
    """Hugging Face Hub への最小のインターフェース（テストでは差し替える）。"""

    def get(self, repo_id: str, revision: str, path: str) -> bytes: ...

    def snapshot(
        self, repo_id: str, revision: str, allow_patterns: list[str], local_dir: Path
    ) -> None: ...

    def paths_info(self, repo_id: str, revision: str, paths: list[str]) -> dict[str, str]: ...


class DefaultHubClient:
    """huggingface_hub を使う実装。匿名で取得する。"""

    def get(self, repo_id: str, revision: str, path: str) -> bytes:
        from huggingface_hub import get_session, hf_hub_url

        url = hf_hub_url(repo_id, path, repo_type="dataset", revision=revision)
        r = get_session().get(url)
        if r.status_code != 200:
            raise SourceError(
                f"取得に失敗した（HTTP {r.status_code}）: {repo_id}@{revision}:{path}"
            )
        return r.content

    def snapshot(
        self, repo_id: str, revision: str, allow_patterns: list[str], local_dir: Path
    ) -> None:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            revision=revision,
            allow_patterns=allow_patterns,
            local_dir=str(local_dir),
        )

    def paths_info(self, repo_id: str, revision: str, paths: list[str]) -> dict[str, str]:
        from huggingface_hub import HfApi

        out: dict[str, str] = {}
        api = HfApi()
        for i in range(0, len(paths), _PATHS_INFO_BATCH):
            for item in api.get_paths_info(
                repo_id, paths[i : i + _PATHS_INFO_BATCH], repo_type="dataset", revision=revision
            ):
                lfs = getattr(item, "lfs", None)
                if lfs is not None and getattr(lfs, "sha256", None):
                    out[item.path] = lfs.sha256
        return out

    def file_ids(self, repo_id: str, revision: str, paths: list[str]) -> dict[str, dict[str, str]]:
        """固定版の各ファイルの照合値。LFS は SHA-256、通常のファイルは git の blob ID（SHA-1）。"""
        from huggingface_hub import HfApi

        out: dict[str, dict[str, str]] = {}
        api = HfApi()
        for i in range(0, len(paths), _PATHS_INFO_BATCH):
            for item in api.get_paths_info(
                repo_id, paths[i : i + _PATHS_INFO_BATCH], repo_type="dataset", revision=revision
            ):
                lfs = getattr(item, "lfs", None)
                if lfs is not None and getattr(lfs, "sha256", None):
                    out[item.path] = {"sha256": lfs.sha256}
                elif getattr(item, "blob_id", None):
                    out[item.path] = {"git_sha1": item.blob_id}
        return out


def _check_relpath(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or not path:
        raise SourceError(f"取得するパスはリポジトリ内の相対パスにする: {path!r}")
    return path


@dataclass
class HuggingFaceSource:
    repo_id: str
    revision: str
    client: HubClient | None = None

    def __post_init__(self) -> None:
        # main・タグ・短縮 SHA は不可。追随しない固定版だけを取得する
        if not _SHA40.match(self.revision):
            raise SourceError(f"revision は 40 桁のコミット SHA にする: {self.revision!r}")
        if self.client is None:
            self.client = DefaultHubClient()

    @property
    def label(self) -> str:
        return f"hf:{self.repo_id}@{self.revision}"

    def read_bytes(self, path: str) -> bytes:
        return self.client.get(self.repo_id, self.revision, _check_relpath(path))

    def _snapshot_into(self, dest: Path, patterns: list[str], keep) -> list[Path]:
        """一時ディレクトリに取得し、keep(相対パス) が真のファイルだけを dest に移す。

        snapshot_download は local_dir にリポジトリ全体のファイル一覧（.cache/huggingface/）を書くので、
        dest に直接取得しない。一時ディレクトリは取得のたびに作り直し、移した後に消す
        （前回の取得の情報が残らないので、改ざんを検知した後の取り直しも確実に行われる）。
        """
        dest.mkdir(parents=True, exist_ok=True)
        moved: list[Path] = []
        with tempfile.TemporaryDirectory(prefix="jpcalc-fetch-") as tmp:
            tmpdir = Path(tmp)
            self.client.snapshot(self.repo_id, self.revision, patterns, tmpdir)
            for f in _files_under(tmpdir):
                rel = str(f.relative_to(tmpdir))
                if not keep(rel):
                    continue
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), target)
                moved.append(target)
        return sorted(moved)

    def fetch_files(self, dest: Path, paths: Sequence[str]) -> list[Path]:
        paths = [_check_relpath(p) for p in paths]
        if not paths:
            return []
        wanted = set(paths)
        self._snapshot_into(dest, list(paths), lambda rel: rel in wanted)
        missing = [p for p in paths if not (dest / p).is_file()]
        if missing:
            raise SourceError(f"取得できなかったファイル {len(missing)} 件: {missing[:5]}")
        return [dest / p for p in paths]

    def lfs_sha256(self, paths: Sequence[str]) -> dict[str, str]:
        return self.client.paths_info(
            self.repo_id, self.revision, [_check_relpath(p) for p in paths]
        )

    def file_ids(self, paths: Sequence[str]) -> dict[str, dict[str, str]]:
        """固定版の照合値（評価用の正解の照合に使う）。"""
        fn = getattr(self.client, "file_ids", None)  # 照合値を返せない取得元は「未照合」になる
        return fn(self.repo_id, self.revision, [_check_relpath(p) for p in paths]) if fn else {}

    def fetch_patterns(self, dest: Path, patterns: Sequence[str]) -> list[Path]:
        """パターン（`*`・`**`）に合うファイルを取得する（評価用の取得だけが使う）。"""
        patterns = [_check_relpath(p) for p in patterns]
        return self._snapshot_into(dest, list(patterns), lambda rel: True)


@dataclass
class LocalSource:
    """開発用：固定版の写しをローカルのディレクトリから読む（root はリポジトリの直下に当たる）。"""

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        if not self.root.is_dir():
            raise SourceError(f"ローカルのデータの場所が無い: {self.root}")

    @property
    def label(self) -> str:
        return f"local:{self.root}"

    def read_bytes(self, path: str) -> bytes:
        f = self.root / _check_relpath(path)
        if not f.is_file():
            raise SourceError(f"ファイルが無い: {f}")
        return f.read_bytes()

    def fetch_files(self, dest: Path, paths: Sequence[str]) -> list[Path]:
        out = []
        for p in paths:
            src = self.root / _check_relpath(p)
            if not src.is_file():
                raise SourceError(f"ファイルが無い: {src}")
            target = dest / p
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            out.append(target)
        return out

    def lfs_sha256(self, paths: Sequence[str]) -> dict[str, str]:
        # ローカルの写しは取得元の照合値を持たない（照合値は索引の値だけになる）
        return {}

    def file_ids(self, paths: Sequence[str]) -> dict[str, dict[str, str]]:
        # ローカルの写しは固定版の照合値を持たない（評価では「未照合」と数える）
        return {}

    def fetch_patterns(self, dest: Path, patterns: Sequence[str]) -> list[Path]:
        from fnmatch import fnmatchcase

        rels = [str(p.relative_to(self.root)) for p in _files_under(self.root)]
        hits = [r for r in rels if any(fnmatchcase(r, _check_relpath(pt)) for pt in patterns)]
        return self.fetch_files(dest, hits)


def _files_under(root: Path) -> list[Path]:
    """root 以下のファイル。snapshot_download が書く管理用のディレクトリ（.cache/）は除く。"""
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file() and ".cache" not in p.relative_to(root).parts]


def all_files_under(root: Path) -> list[Path]:
    """root 以下のすべてのファイル（隠しファイル・.cache/ も含む）。置き場所の検査に使う。"""
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() or p.is_symlink())


def source_from_config(cfg, *, env=None) -> DataSource:
    """コーパスの設定から取得元を作る。local の path は ${VAR} を環境変数・deploy.local.env から展開する。"""
    from ..common.local_settings import lookup_local

    if cfg.source.kind == "huggingface":
        hf = cfg.source.huggingface
        return HuggingFaceSource(hf.repo_id, hf.revision)
    raw = cfg.source.local.path
    m = re.fullmatch(r"\$\{([A-Z0-9_]+)\}", raw)
    path = lookup_local(m.group(1), env=env) if m else raw
    if not path:
        raise SourceError(
            f"{cfg.name}: source.kind=local だが {raw} が未設定（configs/deploy.local.env に書く）"
        )
    return LocalSource(Path(path))

"""データソース。取得の経路だけを持ち、照合は verify.py が共通に行う。

- HuggingFaceSource  … Hugging Face の dataset リポジトリから必要なファイルだけ取得する。既定の経路
- LocalSource        … ローカルのデータセット（manifest.json がある階層）からコピーする。開発用・ネットワークに出られない環境用

どちらも「索引（manifest.json と、あれば SHA256SUMS）」と「文書ファイル」を別々に取得する。
`all` などの対象文書は manifest が無いと決まらないため（pipeline.py が順に呼ぶ）。
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from ..common.local_settings import lookup_local
from ..config import ConfigError, CorpusConfig, expand_vars
from .manifest import MANIFEST, SHA256SUMS

INDEX_FILES: tuple[str, ...] = (MANIFEST, SHA256SUMS)


class FetchError(RuntimeError):
    """取得できないファイルがある。"""


class DataSource(Protocol):
    def describe(self) -> dict[str, str | None]: ...

    def dir_suffix(self) -> str:
        """置き場所 `<corpus>/<版><suffix>` の接尾辞。取得元が違えば別の場所に置く。"""
        ...

    def fetch_index(self, dest: Path) -> list[str]:
        """dest に manifest.json（必須）と SHA256SUMS（任意）を置き、置いたファイル名を返す。"""
        ...

    def fetch_docs(self, dest: Path, doc_ids: Sequence[str], files: Sequence[str]) -> list[str]:
        """dest/<doc_id>/<file> を置き、置いた相対パスを返す。1 件でも無ければ FetchError。"""
        ...


def doc_relpaths(doc_ids: Sequence[str], files: Sequence[str]) -> list[str]:
    return [f"{d}/{f}" for d in doc_ids for f in files]


def _require_index(dest: Path) -> None:
    if not (dest / MANIFEST).exists():
        raise FetchError(
            f"{MANIFEST} を取得できなかった（取得元に無い）。configs/corpora/<corpus>.yaml の source を確かめる"
        )


def _require_files(dest: Path, relpaths: Sequence[str]) -> None:
    missing = [r for r in relpaths if not (dest / r).exists()]
    if missing:
        _raise_missing(missing)


def _raise_missing(missing: Sequence[str]) -> None:
    head = ", ".join(missing[:10]) + (" ほか" if len(missing) > 10 else "")
    raise FetchError(
        f"取得元に無いファイルが {len(missing)} 件ある: {head}（取得元の版が manifest と合っているか確かめる）"
    )


class LocalSource:
    def __init__(self, root: Path) -> None:
        self.root = root

    def describe(self) -> dict[str, str | None]:
        return {"kind": "local", "path": str(self.root)}

    def dir_suffix(self) -> str:
        # 従来の置き場所（`<版>`）を変えない
        return ""

    def _copy(self, rel: str, dest: Path) -> bool:
        src = self.root / rel
        if not src.exists():
            return False
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        # 同じ大きさ・更新時刻のファイルはコピーし直さない（中身は verify.py が SHA-256 で確かめる）
        if dst.exists():
            s, d = src.stat(), dst.stat()
            if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
                return True
        shutil.copy2(src, dst)
        return True

    def fetch_index(self, dest: Path) -> list[str]:
        if not self.root.is_dir():
            raise FetchError(
                f"データセットのディレクトリが無い: {self.root}（source.local.path を確かめる）"
            )
        got = [f for f in INDEX_FILES if self._copy(f, dest)]
        _require_index(dest)
        return got

    def fetch_docs(self, dest: Path, doc_ids: Sequence[str], files: Sequence[str]) -> list[str]:
        rels = doc_relpaths(doc_ids, files)
        missing = [r for r in rels if not self._copy(r, dest)]
        if missing:
            _raise_missing(missing)
        return rels


Downloader = Callable[..., str]


def _default_downloader(**kwargs: Any) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def check_revision(repo_id: str, revision: str | None) -> str:
    """revision は 40 桁のコミット SHA に限る。`main`・タグ・null だと repo の更新で入力が黙って変わる。"""
    if not revision or not _COMMIT_SHA_RE.match(revision):
        raise ConfigError(
            f"{repo_id}: source.huggingface.revision は 40 桁のコミット SHA で固定する（今の値: {revision!r}）"
        )
    return revision


class HuggingFaceSource:
    def __init__(
        self,
        repo_id: str,
        revision: str | None = None,
        *,
        token: str | None = None,
        downloader: Downloader | None = None,
    ) -> None:
        self.repo_id = repo_id
        self.revision = revision
        self.token = token
        self._download = downloader or _default_downloader

    def describe(self) -> dict[str, str | None]:
        return {"kind": "huggingface", "repo_id": self.repo_id, "revision": self.revision}

    def dir_suffix(self) -> str:
        return f"-hf-{(self.revision or 'none')[:12]}"

    def _get(self, dest: Path, patterns: list[str]) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        self._download(
            repo_id=self.repo_id,
            repo_type="dataset",
            revision=self.revision,
            allow_patterns=patterns,
            local_dir=str(dest),
            token=self.token,
        )

    def fetch_index(self, dest: Path) -> list[str]:
        self._get(dest, list(INDEX_FILES))
        _require_index(dest)
        return [f for f in INDEX_FILES if (dest / f).exists()]

    def fetch_docs(self, dest: Path, doc_ids: Sequence[str], files: Sequence[str]) -> list[str]:
        rels = doc_relpaths(doc_ids, files)
        # パターンは文書とファイル名を明示する（ページ画像など不要なファイルを取らない）
        self._get(dest, rels)
        _require_files(dest, rels)
        return rels


def make_source(cfg: CorpusConfig, *, downloader: Downloader | None = None) -> DataSource:
    src = cfg.source
    if src.kind == "local":
        if not src.local.path:
            raise ConfigError(f"{cfg.name}: source.local.path が無い")
        return LocalSource(Path(expand_vars(src.local.path)).expanduser())
    if not src.huggingface.repo_id:
        raise ConfigError(
            f"{cfg.name}: source.kind=huggingface だが source.huggingface.repo_id が未設定（null）"
        )
    return HuggingFaceSource(
        src.huggingface.repo_id,
        check_revision(src.huggingface.repo_id, src.huggingface.revision),
        token=lookup_local("HF_TOKEN"),
        downloader=downloader,
    )

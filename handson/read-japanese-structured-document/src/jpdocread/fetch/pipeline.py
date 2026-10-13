"""取得の順序：索引の取得 → 対象文書の決定 → 文書ファイルの取得 → 照合 → 記録。

2 段に分ける。
- `plan_fetch`    … 索引を一時ディレクトリ（`<data_dir>/<corpus>/_index/`）に取り、対象文書を決める。
                    データセットのディレクトリには何も書かない（--dry-run と確認プロンプトはここまで）
- `execute_fetch` … 計画した索引をそのまま使って（取り直さない）、文書ファイルを取得・照合・記録する

置き場所は `<data_dir>/<corpus>/<dataset_version><取得元の接尾辞>/`（local は接尾辞なし、Hugging Face は
`-hf-<revision の先頭 12 桁>`）。同じ置き場所に中身の違う manifest が既にあれば止める（版名が同じで中身が違う
データを混ぜない）。取得元が違えば置き場所が分かれるので、同じ版名でも衝突しない。
取得の記録（どこから・何を・照合の結果）を `FETCH.json` に残す（data/ は git 管理外）。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..common.paths import GOLD_FILES, PREDICT_FILES
from ..config import CorpusConfig, PipelineConfig
from .manifest import MANIFEST, Manifest, load_manifest, load_sha256sums, sha256_file
from .select import Selection, select_docs
from .sources import INDEX_FILES, DataSource, FetchError
from .verify import VerifyReport, verify_files

FETCH_RECORD = "FETCH.json"
_INDEX_STAGING = "_index"


@dataclass(frozen=True)
class FetchPlan:
    source: DataSource
    corpus: str
    staging_dir: Path
    dataset_dir: Path
    manifest: Manifest
    selection: Selection
    files: tuple[str, ...]

    def discard(self) -> None:
        """一時ディレクトリを消す（--dry-run や確認で中断したとき）。"""
        shutil.rmtree(self.staging_dir, ignore_errors=True)


@dataclass(frozen=True)
class FetchResult:
    dataset_dir: Path
    manifest: Manifest
    selection: Selection
    files: tuple[str, ...]
    report: VerifyReport


def files_for(with_gold: bool) -> tuple[str, ...]:
    return PREDICT_FILES + (GOLD_FILES if with_gold else ())


def plan_fetch(
    source: DataSource,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    data_dir: Path,
    *,
    docs: str | None = None,
    docs_file: Path | None = None,
    slice_name: str | None = None,
    with_gold: bool = False,
) -> FetchPlan:
    staging = data_dir / corpus.name / _INDEX_STAGING
    shutil.rmtree(staging, ignore_errors=True)
    try:
        source.fetch_index(staging)
        manifest = load_manifest(staging / MANIFEST)
        selection = select_docs(
            manifest, corpus, pipeline, docs=docs, docs_file=docs_file, slice_name=slice_name
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return FetchPlan(
        source=source,
        corpus=corpus.name,
        staging_dir=staging,
        dataset_dir=data_dir / corpus.name / f"{manifest.version}{source.dir_suffix()}",
        manifest=manifest,
        selection=selection,
        files=files_for(with_gold),
    )


def _install_index(plan: FetchPlan) -> None:
    """計画で取った索引をデータセットのディレクトリに置く。前回の索引は残さず入れ替える。"""
    dest = plan.dataset_dir
    existing = dest / MANIFEST
    if existing.exists() and sha256_file(existing) != sha256_file(plan.staging_dir / MANIFEST):
        raise FetchError(
            f"{dest} に中身の違う {MANIFEST} がある（同じ版名 {plan.manifest.version!r} で内容が違う）。"
            "取得元を確かめ、不要なら該当ディレクトリを削除してから取り直す"
        )
    dest.mkdir(parents=True, exist_ok=True)
    for name in INDEX_FILES:
        (dest / name).unlink(missing_ok=True)
        staged = plan.staging_dir / name
        if staged.exists():
            shutil.copy2(staged, dest / name)


def execute_fetch(plan: FetchPlan) -> FetchResult:
    try:
        _install_index(plan)
    finally:
        plan.discard()
    dest = plan.dataset_dir
    plan.source.fetch_docs(dest, plan.selection.doc_ids, plan.files)
    sums = load_sha256sums(dest / "SHA256SUMS")
    report = verify_files(dest, plan.manifest, sums, plan.selection.doc_ids, plan.files)
    _write_record(plan, report)
    return FetchResult(dest, plan.manifest, plan.selection, plan.files, report)


def run_fetch(
    source: DataSource,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    data_dir: Path,
    **kwargs: Any,
) -> FetchResult:
    """計画して、そのまま実行する（確認が要らない呼び出し側の近道）。"""
    return execute_fetch(plan_fetch(source, corpus, pipeline, data_dir, **kwargs))


def _write_record(plan: FetchPlan, report: VerifyReport) -> None:
    record = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": plan.source.describe(),
        "dataset_version": plan.manifest.version,
        "selection": plan.selection.as_dict(),
        "files": list(plan.files),
        "verify": report.summary(),
        "unverified": report.unverified,
    }
    (plan.dataset_dir / FETCH_RECORD).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

"""ローカルでの読み取りと採点。CLI の `local read`・`eval` の中身。

- `local_read` … 取得（照合込み）→ 予測用の入力ディレクトリ（doc.pdf へのリンクだけ）→ 作業プロセスで読み取り
                  → out/<run_id>/<corpus>/<doc_id>.json。AI 関数は呼ばない。
- `local_eval` … 正解込みで取得 → 作業プロセスで採点 → results/<run_id>/<corpus>/eval.json。評価 DB には登録しない。

予測用の入力ディレクトリに正解 JSON を置かないので、取得済みのデータに正解があっても予測側からは見えない
（AST ガードに加えた、ローカルでの構造的な分離）。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .common import paths
from .compare import compare_dirs
from .config import CorpusConfig, PipelineConfig
from .fetch.pipeline import FetchResult, run_fetch
from .fetch.sources import DataSource
from .worker import run_worker

# 約款の移植元は契約書の追加キーを出さないので、照合では片方に無ければ比べない
CONTRACT_ONLY_KEYS = ("numbering_scheme", "parties", "defined_terms_detail")


def new_run_id(prefix: str = "local") -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"


@dataclass(frozen=True)
class RunDirs:
    out: Path
    work: Path
    results: Path

    @classmethod
    def for_run(cls, run_id: str, corpus: str, home: Path = paths.HOME) -> RunDirs:
        return cls(
            out=home / "out" / run_id / corpus,
            work=home / "work" / run_id / corpus,
            results=home / "results" / run_id / corpus,
        )


def predict_view(dataset_dir: Path, doc_ids: list[str], dest: Path) -> Path:
    """doc.pdf へのリンクだけを並べたディレクトリを作る（予測側の入力。正解 JSON・manifest は置かない）。

    リンク先をたどれば正解と同じディレクトリに届くので、これは「通常のパスから見えない」分離である。
    read/ がパスを辿らないことは AST ガードで、Snowflake 上ではロール分離で補う。
    """
    if dest.exists():
        shutil.rmtree(dest)
    for d in doc_ids:
        (dest / d).mkdir(parents=True)
        (dest / d / "doc.pdf").symlink_to((dataset_dir / d / "doc.pdf").resolve())
    return dest


def read_options(corpus: CorpusConfig) -> dict:
    return {
        "structure_builder": corpus.structure_builder,
        "parties": corpus.features.parties,
        "defined_terms": corpus.features.defined_terms,
        "stitch_tables": corpus.tables.stitch,
        "known_limits": dict(corpus.known_limits),
    }


def local_read(
    source: DataSource,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    *,
    run_id: str,
    data_dir: Path,
    layout_from: Path | None = None,
    compare_with: Path | None = None,
    home: Path | None = None,
    **select: Any,
) -> dict:
    fetched: FetchResult = run_fetch(source, corpus, pipeline, data_dir, **select)
    doc_ids = list(fetched.selection.doc_ids)
    dirs = RunDirs.for_run(run_id, corpus.name, home or paths.HOME)
    docs = predict_view(fetched.dataset_dir, doc_ids, dirs.work / "docs")
    worker = run_worker(
        "read",
        {
            "doc_ids": doc_ids,
            "options": read_options(corpus),
            "layout_from": str(layout_from) if layout_from else None,
        },
        docs=docs,
        work=dirs.work / "work",
        out=dirs.out,
    )
    summary = {
        "run_id": run_id,
        "corpus": corpus.name,
        "dataset_version": fetched.manifest.version,
        "doc_ids": doc_ids,
        "layout": "from_run" if layout_from else "none",
        "out_dir": str(dirs.out),
        "done": worker["done"],
        "errors": worker["errors"],
    }
    if compare_with:
        summary["compare"] = {
            "with": str(compare_with),
            "mismatches": compare_dirs(
                dirs.out,
                compare_with,
                worker["done"],
                # 約款の移植元だけが契約書の追加キーを出さない。契約書ではキーの欠落も不一致にする
                ignore_missing_keys=CONTRACT_ONLY_KEYS
                if corpus.structure_builder == "yakkan"
                else (),
            ),
        }
    return summary


def local_eval(
    source: DataSource,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    *,
    run_id: str,
    pred_dir: Path,
    data_dir: Path,
    home: Path | None = None,
    **select: Any,
) -> dict:
    fetched = run_fetch(source, corpus, pipeline, data_dir, with_gold=True, **select)
    doc_ids = list(fetched.selection.doc_ids)
    dirs = RunDirs.for_run(run_id, corpus.name, home or paths.HOME)
    worker = run_worker(
        "eval",
        {
            "doc_ids": doc_ids,
            "eval_excluded": list(corpus.eval_excluded),
            "pred_dir": str(pred_dir.resolve()),
            "subsets": {k: v for k, v in corpus.slices.items()},
        },
        docs=fetched.dataset_dir,
        work=dirs.work / "eval",
        out=dirs.work / "eval-out",  # 採点は書き出さないが、作業プロセスの約束として渡す
    )
    result = worker["result"]
    record = {
        "run_id": run_id,
        "corpus": corpus.name,
        "dataset_version": fetched.manifest.version,
        "pred_dir": str(pred_dir),
        "doc_ids": doc_ids,
        "eval_excluded": [d for d in doc_ids if d in set(corpus.eval_excluded)],
        "evaluated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **result,
    }
    dirs.results.mkdir(parents=True, exist_ok=True)
    (dirs.results / "eval.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return record

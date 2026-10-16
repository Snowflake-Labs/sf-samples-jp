"""Snowflake への配置（setup・start が呼ぶ。冪等）。`jpdocread deploy docs|prompt|specs|register-run`。

- docs          取得と照合（fetch）→ doc.pdf を @RAW.DOCS/<corpus>/<doc_id>/ へ PUT → ステージの md5 と照合 → RAW.FILES に台帳
- prompt        供出元の正解から図 few-shot を作り（configs/shots/<corpus>/。git 管理外）、OPS.FIGURE_PROMPT に書く
- specs         ジョブ仕様テンプレート（container/job_specs/）を @APP.SPECS へ PUT
- register-run  RUNS 台帳に run を登録する（同じ run_id が既にあれば止まる。再実行は start.sh --resume）

正解 JSON はここでは Snowflake に載せない（評価ステージへの配置は start.sh --eval のときだけ、run.py が行う）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .common import paths, sf
from .config import CorpusConfig, PipelineConfig
from .fetch.pipeline import FetchResult, run_fetch
from .fetch.sources import DataSource

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")  # RUN_JOB・build_push.sh と同じ規則


class DeployError(RuntimeError):
    """配置の前提が満たされない（ステージと台帳の不一致など）。"""


def _put_path(p: Path) -> str:
    """PUT の引用符の中に埋め込むので、`'` を含むパスは拒む。"""
    s = str(p.resolve())
    if "'" in s:
        raise DeployError(f"パスに ' を含むと PUT できない: {s}")
    return s


def md5_file(p: Path) -> str:
    h = hashlib.md5()  # noqa: S324 — ステージのディレクトリ表の md5 と照合するため（暗号用途ではない）
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pdf_meta(p: Path) -> tuple[int, float, float]:
    import pdfplumber

    with pdfplumber.open(p) as pdf:
        return len(pdf.pages), float(pdf.pages[0].width), float(pdf.pages[0].height)


@dataclass(frozen=True)
class LedgerRow:
    corpus: str
    doc_id: str
    rel_path: str
    size_bytes: int
    md5: str
    sha256: str
    n_pages: int
    page_w_pt: float
    page_h_pt: float
    dataset_version: str | None


def ledger_rows(fetched: FetchResult, corpus: str) -> list[LedgerRow]:
    """取得・照合済みの doc.pdf から入力台帳の行を作る（純粋にローカルのファイルから）。"""
    rows = []
    for d in fetched.selection.doc_ids:
        p = fetched.dataset_dir / d / "doc.pdf"
        n, w, h = pdf_meta(p)
        rows.append(
            LedgerRow(corpus, d, f"{corpus}/{d}/doc.pdf", p.stat().st_size, md5_file(p), sha256_file(p),
                      n, w, h, fetched.manifest.version)
        )  # fmt: skip
    return rows


def stage_mismatches(rows: list[LedgerRow], stage_md5: dict[str, str]) -> list[str]:
    """ステージのディレクトリ表（relative_path → md5）と台帳が合わない文書。"""
    return [r.rel_path for r in rows if stage_md5.get(r.rel_path) != r.md5]


def to_upload(rows: list[LedgerRow], stage_md5: dict[str, str]) -> list[LedgerRow]:
    """ステージに同じ md5 で既にある文書は PUT しない。"""
    return [r for r in rows if stage_md5.get(r.rel_path) != r.md5]


def _stage_md5(conn: SnowflakeConnection, stage: str, prefix: str) -> dict[str, str]:
    sf.query(conn, f"ALTER STAGE {stage} REFRESH")
    listed = sf.query(
        conn,
        f"SELECT relative_path, md5 FROM DIRECTORY(@{stage}) WHERE STARTSWITH(relative_path, %s)",
        (prefix,),
    )
    return {x["relative_path"]: x["md5"] for x in listed}


def put_docs(conn: SnowflakeConnection, fetched: FetchResult, corpus: str) -> dict:
    """doc.pdf を @RAW.DOCS/<corpus>/<doc_id>/ に置き（同じ md5 なら飛ばす）、ステージと照合して RAW.FILES を書く。"""
    rows = ledger_rows(fetched, corpus)
    n = sf.names()
    stage = n.fq("schema_raw", "DOCS")
    todo = to_upload(rows, _stage_md5(conn, stage, f"{corpus}/"))
    for r in todo:
        src = fetched.dataset_dir / r.doc_id / "doc.pdf"
        # パスに `--` を含むので、ローカル・ステージとも引用符で囲む
        sf.query(
            conn,
            f"PUT 'file://{_put_path(src)}' '@{stage}/{corpus}/{r.doc_id}/' AUTO_COMPRESS = FALSE OVERWRITE = TRUE",
        )
    bad = stage_mismatches(rows, _stage_md5(conn, stage, f"{corpus}/"))
    if bad:
        raise DeployError(
            f"ステージの md5 がローカルと一致しない（台帳を書かない）: {bad}。deploy docs を流し直す"
        )
    files = n.fq("schema_raw", "FILES")
    sf.query(
        conn,
        f"DELETE FROM {files} WHERE corpus = %s AND doc_id IN ({','.join(['%s'] * len(rows))})",
        (corpus, *[r.doc_id for r in rows]),
    )
    cur = conn.cursor()
    cur.executemany(
        f"INSERT INTO {files} (corpus, doc_id, rel_path, size_bytes, md5, sha256, n_pages, page_w_pt,"
        " page_h_pt, dataset_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [tuple(r.__dict__.values()) for r in rows],
    )
    cur.close()
    return {
        "corpus": corpus,
        "dataset_version": fetched.manifest.version,
        "n_docs": len(rows),
        "n_put": len(todo),
        "n_pages": sum(r.n_pages for r in rows),
        "doc_ids": [r.doc_id for r in rows],
    }


def gold_files(fetched: FetchResult) -> list[tuple[str, Path]]:
    """評価ステージに置く正解（相対パス, ローカルのパス）。doc.pdf は置かない（予測側の入力と分ける）。"""
    from .common.paths import GOLD_FILES

    out = [("manifest.json", fetched.dataset_dir / "manifest.json")]
    for d in fetched.selection.doc_ids:
        for f in GOLD_FILES:
            p = fetched.dataset_dir / d / f
            if p.exists():
                out.append((f"{d}/{f}", p))
    return out


def gold_manifest_rows(fetched: FetchResult, corpus: str) -> list[tuple]:
    """GOLD.MANIFEST の行（corpus, doc_id, file, 期待値, 実測, 照合済みか）。期待値の無いファイルは未照合（None）。"""
    verified = set(fetched.report.verified)
    rows = []
    for rel, p in gold_files(fetched):
        if "/" not in rel:
            continue  # manifest.json 自体は照合の対象外
        doc_id, file = rel.split("/", 1)
        entry = fetched.manifest.documents.get(doc_id)
        expected = entry.checksums.get(file) if entry else None
        rows.append(
            (corpus, doc_id, file, expected, sha256_file(p), True if rel in verified else None)
        )
    return rows


def put_gold(conn: SnowflakeConnection, fetched: FetchResult, corpus: str) -> dict:
    """--eval のときだけ、正解を @<EVAL_DB>.GOLD.FILES/<corpus>/ に置き、照合の結果を GOLD.MANIFEST に書く。

    conn は評価ロールの接続（予測ロールは評価 DB に触れない）。
    """
    n = sf.names()
    stage = n.fq("schema_gold", "FILES")
    for rel, p in gold_files(fetched):
        sub = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""
        sf.query(
            conn,
            f"PUT 'file://{_put_path(p)}' '@{stage}/{corpus}/{sub}' AUTO_COMPRESS = FALSE OVERWRITE = TRUE",
        )
    sf.query(conn, f"ALTER STAGE {stage} REFRESH")
    # 照合は取得のときに済んでいる（不一致なら fetch が止まる）。ここではその結果を評価 DB に記録する
    rows = gold_manifest_rows(fetched, corpus)
    table = n.fq("schema_gold", "MANIFEST")
    sf.query(
        conn,
        f"DELETE FROM {table} WHERE corpus = %s AND doc_id IN ({','.join(['%s'] * len(fetched.selection.doc_ids))})",
        (corpus, *fetched.selection.doc_ids),
    )
    if rows:
        cur = conn.cursor()
        cur.executemany(
            f"INSERT INTO {table} (corpus, doc_id, file, sha256_manifest, sha256_local, checksum_ok)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            rows,
        )
        cur.close()
    return {"corpus": corpus, "n_files": len(gold_files(fetched)), "n_manifest_rows": len(rows)}


def upload_docs(
    source: DataSource,
    corpus: CorpusConfig,
    pipeline: PipelineConfig,
    *,
    data_dir: Path,
    **select: Any,
) -> dict:
    fetched = run_fetch(source, corpus, pipeline, data_dir, **select)
    n = sf.names()
    conn = sf.connect(role=n.role_predict)
    try:
        return put_docs(conn, fetched, corpus.name)
    finally:
        conn.close()


def load_prompt(
    source: DataSource, corpus: CorpusConfig, pipeline: PipelineConfig, *, data_dir: Path
) -> dict:
    """供出元の正解から図 few-shot を作り、FIGURE_PROMPT に書く（コーパスごとに 1 行）。"""
    from .worker import run_worker

    fetched = run_fetch(source, corpus, pipeline, data_dir, docs=",".join(corpus.figure_shots),
                        docs_file=None, slice_name=None, with_gold=True)  # fmt: skip
    shots_dir = paths.CONFIGS / "shots" / corpus.name
    r = run_worker(
        "shots",
        {"donors": list(corpus.figure_shots)},
        docs=fetched.dataset_dir,
        work=paths.HOME / "work" / "shots" / corpus.name,
        out=paths.HOME / "work" / "shots" / corpus.name / "out",
        shots=shots_dir,
    )
    if "spec" not in r:
        raise DeployError(
            f"図 few-shot を作れない（供出元の取得と configs/corpora/ の figure_shots を確かめる）: {r.get('errors') or r}"
        )
    spec, f = r["spec"], pipeline.figure
    if (spec["model"], spec["prompt_version"]) != (f.model, f.prompt_version):
        raise DeployError(
            f"read/figures.py と pipeline.yaml のモデル／プロンプト版が違う: {spec['model']}/{spec['prompt_version']}"
            f" と {f.model}/{f.prompt_version}"
        )
    if re.search(r"\{(?!\d\})", spec["rules"]):
        raise DeployError(
            "プロンプト本文にプレースホルダ以外の { がある（PROMPT() が NULL を返す。F7）"
        )
    donors = [s["doc_id"] for s in r["shots"]]
    if sorted(donors) != sorted(corpus.figure_shots) or len(spec["shot_crops"]) != 2:
        raise DeployError(f"shot が供出元 2 件と対応しない: {donors} {spec['shot_crops']}")
    by_crop = {s["crop"]: s["doc_id"] for s in r["shots"]}
    n = sf.names()
    table = n.fq("schema_ops", "FIGURE_PROMPT")
    conn = sf.connect(role=n.role_admin)
    try:
        sf.query(conn, f"DELETE FROM {table} WHERE corpus = %s", (corpus.name,))
        sf.query(
            conn,
            f"INSERT INTO {table} (corpus, prompt_version, model, rules, shot_a_doc, shot_a_path, shot_a_json,"
            " shot_b_doc, shot_b_path, shot_b_json, tokens_per_elem, min_max_tokens, retry_parse_error, loaded_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP())",
            (corpus.name, spec["prompt_version"], spec["model"], spec["rules"],
             by_crop[spec["shot_crops"][0]], spec["shot_crops"][0], spec["shot_jsons"][0],
             by_crop[spec["shot_crops"][1]], spec["shot_crops"][1], spec["shot_jsons"][1],
             f.max_tokens_per_node, f.max_tokens_min, f.retry_parse_error),
        )  # fmt: skip
    finally:
        conn.close()
    return {
        "corpus": corpus.name,
        "shots": r["shots"],
        "model": spec["model"],
        "prompt_version": spec["prompt_version"],
    }


def put_specs() -> list[str]:
    n = sf.names()
    stage = n.fq("schema_app", "SPECS")
    specs = sorted((paths.HOME / "container" / "job_specs").glob("*.yaml"))
    if not specs:
        raise DeployError(
            "container/job_specs/*.yaml が無い（リポジトリのジョブ仕様テンプレートが欠けている）"
        )
    conn = sf.connect(role=n.role_admin)
    try:
        for p in specs:
            sf.query(
                conn,
                f"PUT 'file://{_put_path(p)}' '@{stage}/' AUTO_COMPRESS = FALSE OVERWRITE = TRUE",
            )
        sf.query(conn, f"ALTER STAGE {stage} REFRESH")
    finally:
        conn.close()
    return [p.name for p in specs]


def register_run(
    *,
    run_id: str,
    corpus: CorpusConfig,
    doc_ids: list[str],
    slice_name: str,
    image_tag: str,
    dataset_version: str | None,
    config: dict | None = None,
) -> dict:
    """RUNS 台帳に run を 1 行登録する。対象文書は RAW.FILES にあること（S00 が再確認する）。"""
    if not RUN_ID_RE.match(run_id):
        raise DeployError(f"run_id は英数字・_・- の 128 文字以内: {run_id!r}")
    if not IMAGE_TAG_RE.match(image_tag) or image_tag == "latest":
        raise DeployError(
            f"image_tag の形が不正: {image_tag!r}（英数字・_・.・- の 64 文字以内。latest は使えない）"
        )
    overlap = sorted(set(doc_ids) & set(corpus.figure_shots))
    if overlap:
        raise DeployError(
            f"図 few-shot の供出元は対象に入れない（S30 が自動で処理し、評価から除く）: {overlap}"
        )
    n = sf.names()
    runs, files = n.fq("schema_ops", "RUNS"), n.fq("schema_raw", "FILES")
    conn = sf.connect(role=n.role_predict)
    try:
        if sf.query(conn, f"SELECT 1 FROM {runs} WHERE run_id = %s", (run_id,)):
            raise DeployError(f"run_id が既にある: {run_id}（再実行は --resume）")
        have = {
            r["doc_id"]
            for r in sf.query(conn, f"SELECT doc_id FROM {files} WHERE corpus = %s", (corpus.name,))
        }
        missing = sorted(set(doc_ids) - have) + sorted(set(corpus.figure_shots) - have)
        if missing:
            raise DeployError(f"RAW.FILES に無い文書がある（先に deploy docs）: {missing}")
        sf.query(
            conn,
            f"INSERT INTO {runs} (run_id, corpus, slice, docs, donors, eval_excluded, config, image_tag,"
            " dataset_version, status, started_at)"
            " SELECT %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s), %s, %s,"
            " 'REGISTERED', CURRENT_TIMESTAMP()",
            (run_id, corpus.name, slice_name, json.dumps(doc_ids), json.dumps(list(corpus.figure_shots)),
             json.dumps(list(corpus.eval_excluded)), json.dumps(config or {}), image_tag, dataset_version),
        )  # fmt: skip
    finally:
        conn.close()
    return {"run_id": run_id, "corpus": corpus.name, "n_docs": len(doc_ids), "image_tag": image_tag}

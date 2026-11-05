"""SPCS の予測ジョブの入口（`jpcalc job predict --run-id ...`）。

ジョブは予測ロールで動き、次の 2 つのステージだけをマウントする（評価側のステージはマウントしない）：
  /stage/pdfs     予測の入力（<corpus>/<rev>/<pdf_id>.pdf・<corpus>/<rev>/pdf_sha256.json・shots/<corpus>/*.json）
  /stage/results  生成物（<corpus>/<rev>/pdoc/・<corpus>/<rev>/runs/<run_id>/<pdf_id>/）
対象と設定は台帳（RUNS）から読む。台帳で成功済み（STEP_RUNS の P が SUCCEEDED）の PDF は飛ばす（再開）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

PDF_ROOT = Path(os.environ.get("JPCALC_STAGE_PDFS", "/stage/pdfs"))
RESULTS_ROOT = Path(os.environ.get("JPCALC_STAGE_RESULTS", "/stage/results"))


class JobError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    corpus: str
    revision: str
    pdf_ids: list[str]
    use_shots: bool
    max_iter: int | None
    no_cache: bool = False
    fail: dict | None = None  # 故障注入 {"step": "A"|"P", "pdf": <pdf_id>}（運用の試験用）


# 台帳（RUNS）の値はステージ上のパスに入るので、使う前に形を確かめる（予測側が書ける表のため）
_PDF_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,159}$")
_REV = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_run_values(run_id: str, corpus, revision, docs) -> None:
    from .config import CORPUS_NAMES

    bad = []
    if not _RUN_ID.match(run_id or ""):
        bad.append(f"run_id {run_id!r}")
    if corpus not in CORPUS_NAMES:
        bad.append(f"corpus {corpus!r}")
    if not isinstance(revision, str) or not _REV.match(revision):
        bad.append(f"revision {revision!r}")
    bad += [f"pdf_id {d!r}" for d in docs if not isinstance(d, str) or not _PDF_ID.match(d)][:3]
    if bad:
        raise JobError(f"台帳の値の形が正しくない（パスに使わない）: {', '.join(bad)}")


def load_run(conn, run_id: str) -> RunConfig:
    from .common import sf

    rows = sf.query(
        conn,
        f"SELECT corpus, docs, config FROM {sf.fq('schema_ops', 'RUNS')} WHERE run_id = %s",
        (run_id,),
    )
    if len(rows) != 1:
        raise JobError(f"run が RUNS に無い（または重複している）: {run_id}")
    r = rows[0]
    cfg = json.loads(r["config"]) if isinstance(r["config"], str) else (r["config"] or {})
    docs = json.loads(r["docs"]) if isinstance(r["docs"], str) else list(r["docs"] or [])
    if not docs:
        raise JobError(f"run の対象が 0 件: {run_id}")
    _check_run_values(run_id, r["corpus"], cfg.get("revision"), docs)
    return RunConfig(
        run_id=run_id,
        corpus=r["corpus"],
        revision=cfg["revision"],
        pdf_ids=[str(d) for d in docs],
        use_shots=bool(cfg.get("shots", True)),
        max_iter=cfg.get("max_iter"),
        no_cache=bool(cfg.get("no_cache")),
        fail=cfg.get("fail") or None,
    )


def succeeded(conn, run_id: str, step: str = "P") -> set[str]:
    from .common import sf

    rows = sf.query(
        conn,
        f"SELECT doc_id FROM {sf.fq('schema_ops', 'STEP_RUNS')} "
        "WHERE run_id = %s AND step = %s AND status = 'SUCCEEDED'",
        (run_id, step),
    )
    return {r["doc_id"] for r in rows}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def stage_pdfs(rc: RunConfig, root: Path | None = None) -> dict[str, Path]:
    """入力ステージの PDF を照合する（upload が書いた pdf_sha256.json の SHA-256）。照合できない PDF があれば止める。"""
    base = (root or PDF_ROOT) / rc.corpus / rc.revision
    mf = base / "pdf_sha256.json"
    if not mf.is_file():
        raise JobError(f"入力ステージに pdf_sha256.json が無い: {mf}（upload を先に実行する）")
    sha_map = json.loads(mf.read_text(encoding="utf-8"))
    out = {}
    for pid in rc.pdf_ids:
        p = base / f"{pid}.pdf"
        want = (sha_map.get(pid) or {}).get("sha256")
        if not p.is_file() or not want or _sha256(p) != want:
            raise JobError(f"入力ステージの PDF を照合できない: {pid}")
        out[pid] = p
    return out


def run_predict(run_id: str, *, conn=None) -> dict:
    from .common import paths as P
    from .common import sf
    from .pdfread.pdoc import build
    from .predict import d_spec, k_cards, pipeline
    from .predict import shots as PS

    own = conn is None
    conn = conn or sf.connect()
    try:
        rc = load_run(conn, run_id)
        done = succeeded(conn, run_id)
        todo = [p for p in rc.pdf_ids if p not in done]
        if not todo:
            return {"run_id": run_id, "skipped": "all PDFs already succeeded", "n": len(rc.pdf_ids)}
        pdfs = stage_pdfs(rc)
        if rc.no_cache:
            # キャッシュを使わない run：キャッシュキーに run_id を足す（同じ run の再開ではキャッシュに当たる）
            os.environ["JPCALC_CACHE_SALT"] = run_id
        fail = rc.fail or {}
        a_done = succeeded(conn, run_id, "A")
        # 生成物は出力ステージに書く（pipeline の OUT を出力ステージの根に向ける）
        pipeline.OUT = RESULTS_ROOT
        P.OUT = RESULTS_ROOT
        pd = pipeline.pdoc_dir(rc.corpus, rc.revision)
        pd.mkdir(parents=True, exist_ok=True)
        skip_p: list[str] = []
        for pid in todo:
            if fail.get("step") == "A" and fail.get("pdf") == pid:
                sf.record(conn, run_id, "A", pid, "FAILED", n_errors=1, error_text="故障注入（A）")
                skip_p.append(pid)
                continue
            if pid in a_done and (pd / f"{pid}.json").is_file():
                continue  # 段 A は成功済み（--from P・再開）。pdoc を作り直さない
            sf.record(conn, run_id, "A", pid, "RUNNING")
            try:
                doc = build(pid, pdfs[pid])
                (pd / f"{pid}.json").write_text(
                    json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                sf.record(
                    conn,
                    run_id,
                    "A",
                    pid,
                    "SUCCEEDED",
                    n_errors=len(doc["pdoc"]["read_errors"]),
                    output_uri=str(pd / f"{pid}.json"),
                )
            except Exception as e:  # noqa: BLE001  1 PDF の失敗でほかの PDF を止めない（P の load で記録される）
                sf.record(
                    conn,
                    run_id,
                    "A",
                    pid,
                    "FAILED",
                    n_errors=1,
                    error_text=f"{type(e).__name__}: {e}",
                )
        if rc.use_shots:
            sd = PDF_ROOT / "shots"
            k_text = k_cards.render_shots(PS.load(rc.corpus, "k_cards", sd))
            d_text = d_spec.render_shots(PS.load(rc.corpus, "d_spec", sd))
        else:
            k_text = d_text = ""
        if fail.get("step") == "P" and fail.get("pdf") in todo:
            sf.record(
                conn, run_id, "P", fail["pdf"], "FAILED", n_errors=1, error_text="故障注入（P）"
            )
            skip_p.append(fail["pdf"])
        from .config import load_corpus_config, load_pipeline_config

        todo_p = [p for p in todo if p not in skip_p]
        # まとまりごとに段 P を台帳に書く（run_pdfs が書く）。Task の時間制限で切れても、--resume は
        # 終わったまとまりを飛ばす。プロンプトは PDF ごとなので、AI のキャッシュのキーは分け方で変わらない
        chunk = load_pipeline_config().run.chunk_pdfs
        tuning = load_corpus_config(rc.corpus).tuning
        out: dict = {}
        stats: dict = {}
        for i in range(0, len(todo_p), chunk):
            part = pipeline.run_pdfs(
                conn,
                run_id,
                rc.corpus,
                rc.revision,
                todo_p[i : i + chunk],
                k_shots_text=k_text,
                d_shots_text=d_text,
                max_iter=rc.max_iter,
                tuning=tuning,
            )
            for k, v in part.pop("_llm_stats", {}).items():
                stats[k] = stats.get(k, 0) + v
            out.update(part)
        return {
            "run_id": run_id,
            "n_todo": len(todo),
            "n_failed_injected": len(skip_p),
            "n_module": sum(1 for s in out.values() if s.get("module")),
            "llm": stats,
        }
    finally:
        if own:
            conn.close()

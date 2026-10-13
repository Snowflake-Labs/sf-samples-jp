"""Snowflake での読み取り・登録・評価を 1 回流す（`jpdocread run`。scripts/start.sh が呼ぶ）。

  新規    対象を決めて表示（見込みクレジット。all は確認）→ 取得と照合 → doc.pdf を PUT（同じ md5 は飛ばす）
          →（--eval なら正解を評価ステージへ）→ RUNS に登録 → Task グラフを起動 → 完了まで待つ
  再開    --resume <run_id>：同じ run_id で起動し直す。SUCCEEDED の (run_id, step, doc_id) は飛ばすので、
          失敗・未実行の分だけが走り、AI 関数はキャッシュから引く（再課金しない）
  監視    --watch <run_id>：起動済みの run の完了を待って結果を表示する

失敗したら、失敗したステップ・ジョブログの末尾・再実行コマンドを表示して rc=1 で終わる。
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .common import sf

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

    from .config import CorpusConfig, PipelineConfig
    from .fetch.pipeline import FetchPlan, FetchResult
    from .fetch.sources import DataSource

RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
STEP_ORDER = (
    "S00",
    "S10",
    "S20",
    "S30",
    "S40",
    "S50",
    "S55",
    "S60",
    "S70",
)  # sql/tasks/dag.sql と同じ
FAIL_STEPS = ("S20", "S30", "S50")  # 故障注入できるステップ（S20 は 1 文書分の課金がある）
FAIL_RE = re.compile(rf"^({'|'.join(FAIL_STEPS)}):[A-Za-z0-9_.-]+$")
DONE_STATES = ("SUCCEEDED", "INCOMPLETE", "FAILED")


class RunError(RuntimeError):
    """run を始められない・失敗した（理由はメッセージ）。"""


@dataclass(frozen=True)
class RunArgs:
    corpus: str | None = None
    docs: str | None = None
    docs_file: str | None = None
    slice_name: str | None = None
    run_id: str | None = None
    resume: str | None = None
    watch: str | None = None
    from_step: str = "S00"
    fail: str = ""
    eval: bool = False
    yes: bool = False
    poll_seconds: int = 20
    timeout_minutes: int = 180


def validate(a: RunArgs) -> None:
    """Snowflake に触れる前の引数の検査（値は SQL・タスクの CONFIG に入る）。"""
    if sum(bool(x) for x in (a.resume, a.watch)) > 1:
        raise RunError("--resume と --watch は同時に使えない")
    if not (a.resume or a.watch) and not a.corpus:
        raise RunError("新しい run には --corpus が要る")
    for v in (a.run_id, a.resume, a.watch):
        if v and not RUN_ID_RE.match(v):
            raise RunError(f"run_id は英数字・_・- のみ（1〜128 文字）: {v}")
    if a.from_step not in STEP_ORDER:
        raise RunError(f"--from は {'・'.join(STEP_ORDER)} のどれか: {a.from_step}")
    for part in fail_parts(a.fail):
        if not FAIL_RE.match(part):
            raise RunError(
                f"--fail は {'|'.join(FAIL_STEPS)}:<doc_id> のカンマ区切り（空白なし）: {a.fail}"
            )


def fail_parts(spec: str) -> list[str]:
    return [p for p in spec.split(",") if p] if spec else []


def check_fail_docs(spec: str, doc_ids: list[str]) -> None:
    """--fail の文書が run の対象に入っていること（入っていなければ注入が黙って効かない）。"""
    bad = sorted({p.split(":", 1)[1] for p in fail_parts(spec)} - set(doc_ids))
    if bad:
        raise RunError(f"--fail の文書がこの run の対象に無い: {bad}")


def new_run_id(corpus: str, label: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{corpus}_{re.sub(r'[^A-Za-z0-9_-]', '-', label)}"[:128]


def graph_config(run_id: str, from_step: str, skip_eval: bool) -> str:
    """EXECUTE TASK … USING CONFIG に渡す JSON（値は検査済み）。"""
    return json.dumps({"run_id": run_id, "from": from_step, "skip_eval": skip_eval})


@dataclass
class Progress:
    """STEP_RUNS の集計（ステップ → 件数）を 1 行にする。"""

    rows: list[dict] = field(default_factory=list)

    def line(self) -> str:
        by = {r["step"]: r for r in self.rows}
        parts = []
        for s in STEP_ORDER:
            r = by.get(s)
            if not r:
                continue
            mark = f"{r['ok']}✓"
            if r["ng"]:
                mark += f" {r['ng']}✗"
            if r["running"]:
                mark += f" {r['running']}…"
            parts.append(f"{s} {mark}")
        return "  ".join(parts) or "（まだ記録なし）"


def resume_hint(run_id: str, *, eval_: bool) -> str:
    return f"scripts/start.sh --resume {run_id}" + (" --eval" if eval_ else "")


# ---------------------------------------------------------------- Snowflake I/O


def _log(msg: str, *, error: bool = False) -> None:
    """進捗は stdout、失敗の報告は stderr に出す（どちらも [run] を付ける）。"""
    print(f"[run] {msg}", file=sys.stderr if error else sys.stdout, flush=True)


def _confirmed(msg: str) -> bool:
    return sys.stdin.isatty() and input(f"{msg} [y/N] ").strip().lower() == "y"


def _one(conn: SnowflakeConnection, sql: str, params: tuple | None = None) -> Any:
    rows = sf.query(conn, sql, params)
    return next(iter(rows[0].values())) if rows else None


def _use_predict_role(conn: SnowflakeConnection) -> None:
    """予測ロールに切り替える（SECONDARY ROLES は NONE。評価 DB に触れない）。"""
    sf.query(conn, f"USE ROLE {sf.names().role_predict}")
    sf.query(conn, "USE SECONDARY ROLES NONE")


def _plan_targets(
    a: RunArgs, source: DataSource, corpus: CorpusConfig, pipeline: PipelineConfig
) -> FetchPlan:
    """対象を決めて見込みを表示し、取得の計画を返す（供出元の混入・確認の拒否・--fail の不一致で止まる）。"""
    from .common.paths import DATA_DIR
    from .fetch.pipeline import plan_fetch

    select = {
        "docs": a.docs,
        "docs_file": Path(a.docs_file) if a.docs_file else None,
        "slice_name": a.slice_name,
    }
    plan = plan_fetch(source, corpus, pipeline, DATA_DIR, with_gold=a.eval, **select)
    sel = plan.selection
    _log(
        f"対象：{corpus.name} {len(sel.doc_ids)} 文書・{sel.pages} ページ・見込み約 {sel.estimated_credits:.1f} クレジット"
        f"（{sel.how}。目安で請求額ではない）"
    )
    for d in sel.doc_ids:
        _log(f"  {d}{'（評価から除外）' if d in sel.eval_excluded else ''}")
    donors_in = sorted(set(sel.doc_ids) & set(corpus.figure_shots))
    if donors_in:
        plan.discard()
        raise RunError(
            f"図 few-shot の供出元は対象に入れない（S30 が自動で処理し、評価から除く）: {donors_in}"
        )
    if sel.needs_confirmation and not a.yes and not _confirmed("課金が大きい。実行しますか？"):
        plan.discard()
        raise RunError("中止した（確認なしで流すなら --yes）")
    check_fail_docs(a.fail, list(sel.doc_ids))
    return plan


def _put_inputs(
    conn: SnowflakeConnection,
    a: RunArgs,
    corpus: CorpusConfig,
    fetched: FetchResult,
    donors: FetchResult,
) -> None:
    """doc.pdf（対象と供出元）を予測ロールで PUT し、--eval なら正解を評価ロールで評価ステージに置く。"""
    from .deploy import put_docs, put_gold

    _use_predict_role(conn)
    put = put_docs(conn, fetched, corpus.name)
    put_d = put_docs(conn, donors, corpus.name)
    _log(
        f"PUT：{put['n_put']}/{put['n_docs']} 文書（同じ md5 は飛ばした）・供出元 {put_d['n_put']}/{put_d['n_docs']}"
    )
    if a.eval:
        ev = sf.connect(role=sf.names().role_eval)
        try:
            g = put_gold(ev, fetched, corpus.name)
        finally:
            ev.close()
        _log(f"正解を評価ステージへ：{g['n_files']} ファイル（評価ロールで置いた）")


def _register_new_run(
    conn: SnowflakeConnection, a: RunArgs, corpus: CorpusConfig, fetched: FetchResult, tag: str
) -> str:
    """RUNS 台帳に新しい run を RUNNING で登録して run_id を返す（同じ run_id が既にあれば止まる）。"""
    sel = fetched.selection
    run_id = a.run_id or new_run_id(
        corpus.name, "custom" if (a.docs or a.docs_file) else (sel.how.split(":")[-1])
    )
    runs = sf.names().fq("schema_ops", "RUNS")
    if _one(conn, f"SELECT COUNT(*) FROM {runs} WHERE run_id = %s", (run_id,)):
        raise RunError(f"run_id が既にある: {run_id}（再実行は --resume）")
    sf.query(
        conn,
        f"INSERT INTO {runs} (run_id, corpus, slice, docs, donors, eval_excluded, config, image_tag, dataset_version,"
        " status, started_at) SELECT %s, %s, %s, PARSE_JSON(%s), PARSE_JSON(%s), PARSE_JSON(%s),"
        " OBJECT_CONSTRUCT('fail_docs', %s, 'skip_eval', %s), %s, %s, 'RUNNING', CURRENT_TIMESTAMP()",
        (run_id, corpus.name, "custom" if (a.docs or a.docs_file) else sel.how, json.dumps(list(sel.doc_ids)),
         json.dumps(list(corpus.figure_shots)), json.dumps(list(corpus.eval_excluded)), a.fail, not a.eval,
         tag, fetched.manifest.version),
    )  # fmt: skip
    _log(f"登録：run_id={run_id}（image {tag}{'・評価あり' if a.eval else ''}）")
    return run_id


def prepare_new(a: RunArgs, conn: SnowflakeConnection) -> dict:
    """対象を決めて取得・照合し、PUT して RUNS に登録する。登録した run の情報を返す。"""
    from .common.local_settings import lookup_local
    from .common.paths import DATA_DIR
    from .config import load_corpus_config, load_pipeline_config
    from .fetch.pipeline import execute_fetch
    from .fetch.sources import make_source

    corpus = load_corpus_config(a.corpus)
    pipeline = load_pipeline_config()
    source = make_source(corpus)
    fetched = execute_fetch(_plan_targets(a, source, corpus, pipeline))
    # 供出元（図 few-shot の例）も S30 が読むので、予測用のファイルを取得して置く（正解は置かない）
    donors = run_fetch_donors(source, corpus, pipeline, DATA_DIR)
    tag = lookup_local("IMAGE_TAG")
    if not tag:
        raise RunError(
            "IMAGE_TAG が無い（configs/deploy.local.env）。先に scripts/setup.sh を実行する"
        )
    _put_inputs(conn, a, corpus, fetched, donors)
    run_id = _register_new_run(conn, a, corpus, fetched, tag)
    return {"run_id": run_id, "eval": a.eval, "doc_ids": list(fetched.selection.doc_ids)}


def run_fetch_donors(
    source: DataSource, corpus: CorpusConfig, pipeline: PipelineConfig, data_dir: Path
) -> FetchResult:
    from .fetch.pipeline import run_fetch

    return run_fetch(source, corpus, pipeline, data_dir, docs=",".join(corpus.figure_shots),
                     docs_file=None, slice_name=None)  # fmt: skip


def _put_gold_for_resume(corpus_name: str, docs: list[str]) -> None:
    """再開で --eval を付けたとき、登録済みの対象文書の正解を取得・照合し、評価ロールで評価ステージに置く。"""
    from .common.paths import DATA_DIR
    from .config import load_corpus_config, load_pipeline_config
    from .deploy import put_gold
    from .fetch.pipeline import run_fetch
    from .fetch.sources import make_source

    corpus = load_corpus_config(corpus_name)
    fetched = run_fetch(make_source(corpus), corpus, load_pipeline_config(), DATA_DIR,
                        docs=",".join(docs), docs_file=None, slice_name=None, with_gold=True)  # fmt: skip
    ev = sf.connect(role=sf.names().role_eval)
    try:
        g = put_gold(ev, fetched, corpus.name)
    finally:
        ev.close()
    _log(f"正解を評価ステージへ：{g['n_files']} ファイル（再開で評価を足した。評価ロールで置いた）")


def prepare_resume(a: RunArgs, conn: SnowflakeConnection) -> dict:
    from .common.local_settings import lookup_local

    _use_predict_role(conn)
    runs = sf.names().fq("schema_ops", "RUNS")
    rows = sf.query(
        conn, f"SELECT corpus, docs, config, status FROM {runs} WHERE run_id = %s", (a.resume,)
    )
    if not rows:
        raise RunError(
            f"run が RUNS 台帳に無い: {a.resume}（run_id を確かめる。再開できるのは登録済みの run だけ）"
        )
    docs = sf.as_list(rows[0]["docs"])
    cfg = (
        json.loads(rows[0]["config"])
        if isinstance(rows[0]["config"], str)
        else (rows[0]["config"] or {})
    )
    check_fail_docs(a.fail, docs)
    # 評価の有無は登録時の値を引き継ぐ。再開で --eval を付けたときだけ評価する側に上書きする
    eval_ = a.eval or not bool(cfg.get("skip_eval", True))
    if a.eval:
        # 再開で評価を足すときも、新規の run と同じく対象文書の正解を取得・照合して評価ステージに置く
        # （置かないと、前の別 run が残した正解の有無で結果が変わる）
        _put_gold_for_resume(str(rows[0]["corpus"]), docs)
    tag = lookup_local("IMAGE_TAG")
    sf.query(
        conn,
        f"UPDATE {runs} SET status = 'RUNNING', ended_at = NULL, message = NULL, image_tag = COALESCE(%s, image_tag),"
        " config = OBJECT_INSERT(OBJECT_INSERT(config, 'fail_docs', %s, TRUE), 'skip_eval', %s, TRUE)"
        " WHERE run_id = %s",
        (tag, a.fail, not eval_, a.resume),
    )
    _log(f"再開：run_id={a.resume} from={a.from_step}（--fail は付けた値で置き換える：'{a.fail}'）")
    return {"run_id": a.resume, "eval": eval_, "doc_ids": docs, "prev_status": rows[0]["status"]}


def launch(conn: SnowflakeConnection, run_id: str, from_step: str, eval_: bool) -> str:
    n = sf.names()
    root = n.fq("schema_ops", "T_S00")
    launched_at = _one(conn, "SELECT TO_VARCHAR(DATEADD('second', -5, CURRENT_TIMESTAMP()))")
    cfg = graph_config(run_id, from_step, skip_eval=not eval_)
    try:
        sf.query(conn, f"EXECUTE TASK {root} USING CONFIG = $${cfg}$$")
    except Exception as e:  # noqa: BLE001 — 理由を付けて止める
        raise RunError(
            f"Task グラフを起動できない（前の実行が終わっていない可能性。SHOW TASKS で確認）: {e}"
        ) from e
    _log(f"起動：EXECUTE TASK {root} USING CONFIG {cfg}")
    return launched_at


def active_graphs(conn: SnowflakeConnection) -> int:
    """自分の DB・スキーマのグラフで実行中のもの（同名のルートを持つ別プロジェクトは数えない。移植元 T16.9）。"""
    n = sf.names()
    return int(
        _one(
            conn,
            f"SELECT COUNT(*) FROM TABLE({n.db}.INFORMATION_SCHEMA.CURRENT_TASK_GRAPHS(ROOT_TASK_NAME => 'T_S00'))"
            " WHERE database_name = %s AND schema_name = %s",
            (n.db, n.schema_ops),
        )
        or 0
    )


def progress(conn: SnowflakeConnection, run_id: str) -> Progress:
    rows = sf.query(
        conn,
        f"SELECT step, COUNT_IF(status = 'SUCCEEDED') AS ok, COUNT_IF(status = 'FAILED') AS ng,"
        f" COUNT_IF(status = 'RUNNING') AS running FROM {sf.ops()}.STEP_RUNS WHERE run_id = %s GROUP BY step",
        (run_id,),
    )
    return Progress(rows)


def finished(active: int, status: str | None, seen: bool, waited_s: float, grace_s: float) -> bool:
    """グラフが終わったか。起動直後はまだ CURRENT_TASK_GRAPHS に出ないことがあるので、
    一度でも実行中を見たか、run が終わりの状態になったか、猶予を過ぎたときだけ「終わった」とする。"""
    if active:
        return False
    return seen or (status in DONE_STATES) or waited_s >= grace_s


def wait(conn: SnowflakeConnection, run_id: str, a: RunArgs, grace_s: float = 180) -> str:
    t0 = time.time()
    deadline = t0 + a.timeout_minutes * 60
    last = ""
    seen = False
    time.sleep(min(a.poll_seconds, 10))
    while True:
        line = progress(conn, run_id).line()
        if line != last:
            _log(line)
            last = line
        active = active_graphs(conn)
        seen = seen or active > 0
        status = _one(conn, f"SELECT status FROM {sf.ops()}.RUNS WHERE run_id = %s", (run_id,))
        if finished(active, status, seen, time.time() - t0, grace_s):
            break
        if time.time() > deadline:
            raise RunError(
                f"{a.timeout_minutes} 分たっても終わらない（グラフは動いたまま）。--watch {run_id} で待ち直せる"
            )
        time.sleep(a.poll_seconds)
    return (
        _one(conn, f"SELECT status FROM {sf.ops()}.RUNS WHERE run_id = %s", (run_id,)) or "UNKNOWN"
    )


def report_failure(conn: SnowflakeConnection, run_id: str, launched_at: str | None) -> None:
    n = sf.names()
    for r in sf.query(
        conn,
        f"SELECT step, doc_id, LEFT(error_text, 400) AS error FROM {sf.ops()}.STEP_RUNS"
        " WHERE run_id = %s AND status = 'FAILED' ORDER BY step, doc_id LIMIT 20",
        (run_id,),
    ):
        _log(
            f"  失敗 {r['step']} {r['doc_id']}: {(r['error'] or '').splitlines()[0] if r['error'] else ''}",
            error=True,
        )
    if launched_at:
        for r in sf.query(
            conn,
            f"SELECT name, LEFT(error_message, 300) AS err FROM TABLE({n.db}.INFORMATION_SCHEMA.TASK_HISTORY("
            "SCHEDULED_TIME_RANGE_START => DATEADD('hour', -12, CURRENT_TIMESTAMP()), ERROR_ONLY => TRUE,"
            " RESULT_LIMIT => 200)) WHERE database_name = %s AND schema_name = %s AND scheduled_time >= %s::TIMESTAMP_LTZ"
            " ORDER BY scheduled_time",
            (n.db, n.schema_ops, launched_at),
        ):
            _log(f"  タスク {r['name']}: {r['err']}", error=True)
        for r in sf.query(
            conn,
            f"SELECT step, job_name, RIGHT(logs, 1500) AS logs FROM {sf.ops()}.JOBS WHERE run_id = %s"
            " AND status = 'FAILED' AND started_at >= %s::TIMESTAMP_LTZ ORDER BY started_at DESC LIMIT 1",
            (run_id, launched_at),
        ):
            _log(f"  ジョブ {r['step']} のログ末尾：\n{r['logs']}", error=True)


def report_success(conn: SnowflakeConnection, run_id: str, eval_: bool) -> dict:
    n = sf.names()
    out = n.fq("schema_output")
    n_json = _one(conn, f"SELECT detail:n_json::INT FROM {sf.ops()}.STEP_RUNS WHERE run_id = %s AND step = 'S70'",
                  (run_id,))  # fmt: skip
    counts = {
        t: int(_one(conn, f"SELECT COUNT(*) FROM {out}.{t} WHERE run_id = %s", (run_id,)) or 0)
        for t in ("DOCUMENTS", "ELEMENTS", "TABLES", "FIGURES", "REFS", "PARTIES", "DEFINED_TERMS")
    }
    _log(
        f"完了：run_id={run_id}  出力 JSON {n_json} 件  @{n.fq('schema_output', 'RESULTS')}/{run_id}/"
    )
    _log("登録表：" + "・".join(f"{t} {c}" for t, c in counts.items()))
    summary = {"run_id": run_id, "n_json": n_json, "registered": counts}
    if eval_:
        ev = sf.connect(role=n.role_eval)
        try:
            rows = sf.query(
                ev,
                f"SELECT n_docs, excluded_shot_donors, citation_error_rate, citation_coverage, text_cer,"
                f" article_recall, table_cell_f1, figure_edge_f1, refs_recall_reachable, parties_f1, terms_f1"
                f" FROM {n.fq('schema_results', 'V_RUN_SUMMARY')} WHERE pred_run_id = %s",
                (run_id,),
            )
        finally:
            ev.close()
        if rows:
            summary["eval"] = rows[0]
            _log("評価：" + "  ".join(f"{k}={v}" for k, v in rows[0].items()))
    return summary


def execute(a: RunArgs) -> int:
    validate(a)
    conn = sf.connect(role=sf.names().role_predict)
    try:
        if a.watch:
            rows = sf.query(
                conn, f"SELECT config FROM {sf.ops()}.RUNS WHERE run_id = %s", (a.watch,)
            )
            if not rows:
                raise RunError(
                    f"run が RUNS 台帳に無い: {a.watch}（run_id を確かめる。待てるのは登録済みの run だけ）"
                )
            cfg = (
                json.loads(rows[0]["config"])
                if isinstance(rows[0]["config"], str)
                else rows[0]["config"]
            )
            info = {"run_id": a.watch, "eval": not bool((cfg or {}).get("skip_eval", True))}
            launched_at = None
        else:
            info = prepare_resume(a, conn) if a.resume else prepare_new(a, conn)
            try:
                launched_at = launch(conn, info["run_id"], a.from_step, info["eval"])
            except RunError as e:
                # 起動できなければ台帳を RUNNING のまま残さない（再開は元の状態に、新規は FAILED に戻す）
                sf.query(
                    conn,
                    f"UPDATE {sf.ops()}.RUNS SET status = %s, message = %s WHERE run_id = %s",
                    (info.get("prev_status") or "FAILED", str(e)[:1000], info["run_id"]),
                )
                raise
        status = wait(conn, info["run_id"], a)
        if status != "SUCCEEDED":
            report_failure(conn, info["run_id"], launched_at)
            _log(
                f"run {info['run_id']} は {status} で終わった。原因を直してから：{resume_hint(info['run_id'], eval_=info['eval'])}",
                error=True,
            )
            return 1
        report_success(conn, info["run_id"], info["eval"])
        return 0
    finally:
        conn.close()

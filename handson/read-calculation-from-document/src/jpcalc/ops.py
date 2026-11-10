"""Snowflake の運用の操作：setup・ロール分離の検証・予測用のアップロード・run の起動と状態。

どの操作も名前を configs/deploy.env の接頭辞から組み立て（common/names.py）、接続名を git 管理外の設定から読む。
予測用のアップロードは照合済みの PDF・照合値・手本・ジョブ仕様だけを置く（正解は置かない）。
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path

from .common import sf, sqltpl
from .common.envfile import read_env_file
from .common.local_settings import lookup_local
from .common.paths import DEPLOY_ENV, HOME, WORK

RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TAG = re.compile(r"^[0-9]{14}$")


class OpsError(RuntimeError):
    pass


def deploy_values(user: str | None = None) -> dict[str, str]:
    env = read_env_file(DEPLOY_ENV)
    return sqltpl.variables(
        sf.names(),
        warehouse_size=env.get("WAREHOUSE_SIZE", "XSMALL"),
        compute_pool_family=env.get("COMPUTE_POOL_FAMILY", "CPU_X64_XS"),
        image_name=env.get("IMAGE_NAME", "jpcalc"),
        user=user,
    )


def run_files(conn, files, values) -> int:
    n = 0
    for f in files:
        for i, st in enumerate(sqltpl.split_statements(sqltpl.render_file(f, values)), 1):
            try:
                sf.query(conn, st)
            except Exception as e:  # どの文で止まったかを示す（直してから setup を流し直す。冪等）
                head = " ".join(st.split())[:160]
                raise OpsError(f"{f} の {i} 文目で失敗した: {head} … → {e}") from e
            n += 1
    return n


def setup(conn) -> int:
    """setup の SQL を順に実行する（冪等）。conn は ACCOUNTADMIN でログインしたもの。"""
    user = sf.query(conn, "SELECT CURRENT_USER() AS u")[0]["u"]
    v = deploy_values(user)
    n = run_files(conn, sqltpl.SETUP_FILES, v)
    # ジョブ仕様のひな型を置く（予測ロールが読む。正解は含まない）
    sf.query(conn, f"USE ROLE {v['role_admin']}")
    for name in ("predict.yaml", "evaluate.yaml"):
        _put(conn, HOME / "container" / "job_specs" / name, f"@{v['db']}.{v['schema_app']}.SPECS")
    sf.query(conn, f"ALTER STAGE {v['db']}.{v['schema_app']}.SPECS REFRESH")
    return n


def parse_cases(text: str) -> list[tuple[str, str]]:
    """roles.sql の (期待, 文) の組。期待は ok か fail。"""
    out, expect = [], None
    for line in text.splitlines():
        m = re.match(r"^-- expect: (ok|fail)$", line)
        if m:
            expect = m.group(1)
            continue
        if expect and line.strip() and not line.startswith("--"):
            out.append((expect, line.strip()))
            expect = None
    return out


def verify_roles(conn) -> list[dict]:
    """ロール分離の各ケースを実行し、期待と照合した結果を返す。"""
    v = deploy_values()
    cases = parse_cases(sqltpl.render_file(sqltpl.VERIFY_FILE, v))
    if not cases:
        raise OpsError("ロール分離の検証ケースが 0 件")
    res = []
    for expect, line in cases:
        try:
            for st in [s.strip() for s in line.split(";") if s.strip()]:
                sf.query(conn, st)
            got, err = "ok", None
        except Exception as e:  # noqa: BLE001
            got, err = "fail", str(e).splitlines()[0][:160]
        res.append({"expect": expect, "got": got, "sql": line, "error": err})
    return res


# AI_CALL（sql/procedures/ai_call.sql）と同じモデル名の規則。動的な SQL に入れる前に確かめる
_MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
CROSS_REGION_PARAM = "CORTEX_ENABLED_CROSS_REGION"


def check_model(conn, model: str) -> dict:
    """設定のモデルを AI_COMPLETE で 1 回呼び、使えるかを確かめる（出力は数トークン。setup がビルドの前に呼ぶ）。

    使えないときは、アカウントのクロスリージョン推論の設定（CORTEX_ENABLED_CROSS_REGION）の今の値を読めれば添える。
    設定は変えない。
    """
    if not _MODEL_NAME.match(model or ""):
        raise OpsError(f"モデル名に使えない文字がある: {model!r}")
    try:
        sf.query(
            conn,
            f"SELECT AI_COMPLETE(model => '{model}', prompt => 'Reply with OK.', "
            "model_parameters => OBJECT_CONSTRUCT('temperature', 0, 'max_tokens', 8)) AS r",
        )
        return {"ok": True, "model": model, "error": None, "cross_region": None}
    except Exception as e:  # noqa: BLE001  使えない理由をそのまま返す
        err = str(e).splitlines()[0][:300]
    cross = None
    try:
        rows = sf.query(conn, f"SHOW PARAMETERS LIKE '{CROSS_REGION_PARAM}' IN ACCOUNT")
        cross = rows[0].get("value") if rows else None
    except Exception:  # noqa: BLE001, S110  読めなければ添えない
        pass
    return {"ok": False, "model": model, "error": err, "cross_region": cross}


_SAFE_PATH = re.compile(r"^[^'\\\n]+$")


def _put(conn, path: Path, stage_dir: str) -> None:
    if not (_SAFE_PATH.match(path.as_posix()) and _SAFE_PATH.match(stage_dir)):
        raise OpsError(f"PUT のパスに使えない文字がある: {path}")
    # PUT のパスは引用符で囲む（空白・記号を含むパスのため）。上書きし、圧縮しない
    sf.query(
        conn, f"PUT 'file://{path.as_posix()}' '{stage_dir}' OVERWRITE = TRUE AUTO_COMPRESS = FALSE"
    )


def upload_predict(
    conn, corpus: str, rev: str, pdf_ids: list[str], corpus_root: Path, *, shots: bool
) -> dict:
    """照合済みの PDF を <corpus>/<rev>/<pdf_id>.pdf に、照合値を pdf_sha256.json に、手本を shots/ に置く。"""
    from .pdfread.run import load_record

    v = deploy_values()
    record = load_record(corpus_root)
    bad = [p for p in pdf_ids if (record.get(p) or {}).get("verify") != "verified"]
    if bad:
        raise OpsError(f"照合済みでない PDF は置かない: {bad}")
    stage = f"@{v['db']}.{v['schema_raw']}.PDFS"
    sha_map = {p: {"sha256": record[p]["sha256_actual"]} for p in pdf_ids}
    with tempfile.TemporaryDirectory(prefix="jpcalc_up_") as tmp:
        t = Path(tmp)
        for p in pdf_ids:
            dst = t / f"{p}.pdf"
            dst.write_bytes((corpus_root / record[p]["local_path"]).read_bytes())
            _put(conn, dst, f"{stage}/{corpus}/{rev}/")
        # 既存の照合値を残して足す（ほかの run の PDF の照合値を消さない）
        mf = t / "pdf_sha256.json"
        old = _read_stage_json(conn, f"{stage}/{corpus}/{rev}/pdf_sha256.json")
        mf.write_text(json.dumps(old | sha_map, ensure_ascii=False, indent=1), encoding="utf-8")
        _put(conn, mf, f"{stage}/{corpus}/{rev}/")
    n_shots = 0
    if shots:
        for name in ("k_cards.json", "d_spec.json"):
            src = WORK / "shots" / corpus / name
            if not src.is_file():
                raise OpsError(f"手本がありません: {src}（jpcalc make-shots --corpus {corpus}）")
            _put(conn, src, f"{stage}/shots/{corpus}/")
            n_shots += 1
    sf.query(conn, f"ALTER STAGE {v['db']}.{v['schema_raw']}.PDFS REFRESH")
    return {"stage": stage, "n_pdfs": len(pdf_ids), "n_shots": n_shots}


def _read_stage_json(conn, path: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="jpcalc_get_") as tmp:
        try:
            sf.query(conn, f"GET '{path}' 'file://{tmp}/'")
        except Exception:  # noqa: BLE001  無ければ空
            return {}
        f = Path(tmp) / Path(path).name
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def image_repo_url(conn) -> str:
    v = deploy_values()
    rows = sf.query(conn, f"SHOW IMAGE REPOSITORIES IN SCHEMA {v['db']}.{v['schema_app']}")
    for r in rows:
        if r.get("name") == "IMAGES":
            return r["repository_url"]
    raise OpsError("イメージリポジトリが無い（setup を先に実行する）")


def record_tag(conn, tag: str, local_env: Path | None = None) -> None:
    """push したタグが SHOW IMAGES にあることを確かめ、deploy.local.env の IMAGE_TAG に書く（ほかのキーは変えない）。"""
    from .common.paths import DEPLOY_LOCAL_ENV

    if not TAG.match(tag):
        raise OpsError(f"タグの形が不正: {tag!r}")
    v = deploy_values()
    rows = sf.query(conn, f"SHOW IMAGES IN IMAGE REPOSITORY {v['db']}.{v['schema_app']}.IMAGES")
    if not any(r.get("tags") == tag or tag in str(r.get("tags")) for r in rows):
        raise OpsError(f"push したタグ {tag} が SHOW IMAGES に無い")
    p = local_env or DEPLOY_LOCAL_ENV
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    line = f"IMAGE_TAG={tag}"
    if re.search(r"(?m)^IMAGE_TAG=", text):
        text = re.sub(r"(?m)^IMAGE_TAG=.*$", line, text)
    else:
        text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    p.write_text(text, encoding="utf-8")


def image_tag() -> str:
    tag = lookup_local("IMAGE_TAG") or ""
    if not TAG.match(tag):
        raise OpsError("イメージのタグがありません（scripts/build_push.sh を先に実行する）")
    return tag


def start_run(
    conn,
    run_id: str,
    corpus: str,
    rev: str,
    pdf_ids: list[str],
    *,
    shots: bool,
    declaration: str | None,
    max_iter: int | None = None,
    evaluate: bool = False,
    no_cache: bool = False,
    fail: dict | None = None,
    from_step: str | None = None,
) -> None:
    """RUNS に run を書いて Task グラフを起動する。同じ run_id が既にあれば（再開）台帳を残して起動し直す。"""
    if not RUN_ID.match(run_id):
        raise OpsError(f"run_id に使えない文字がある: {run_id!r}")
    v = deploy_values()
    runs = sf.fq("schema_ops", "RUNS")
    tag = image_tag()
    cfg = {
        "revision": rev,
        "shots": shots,
        "max_iter": max_iter,
        "declaration": declaration,
        "eval": evaluate,
        "no_cache": no_cache,
        "fail": fail,
        **ai_signature(),
    }
    exists = sf.query(conn, f"SELECT COUNT(*) AS n FROM {runs} WHERE run_id = %s", (run_id,))[0][
        "n"
    ]
    if exists:
        row = sf.query(
            conn, f"SELECT corpus, docs, config, image_tag FROM {runs} WHERE run_id = %s", (run_id,)
        )[0]
        old = json.loads(row["config"]) if isinstance(row["config"], str) else (row["config"] or {})
        if (
            row["corpus"] != corpus
            or sorted(json.loads(row["docs"])) != sorted(pdf_ids)
            or old.get("revision") != rev
            or bool(old.get("shots", True)) != shots
            or bool(old.get("no_cache")) != no_cache
        ):
            raise OpsError(
                f"再開の対象・版・手本の有無・キャッシュの扱いが元の run と違う: {run_id}"
            )
        # 1 つの run の PDF を同じイメージで作る（再開でイメージを変えない）
        if row["image_tag"] != tag:
            raise OpsError(
                f"再開のイメージ {tag} が元の run のイメージ {row['image_tag']} と違う: {run_id}"
            )
        if from_step == "E" and not evaluate:
            raise OpsError("--from E は評価だけをやり直す。--eval と一緒に指定する")
        if from_step:
            prepare_from(conn, run_id, pdf_ids, from_step, tag)
        # 故障注入と評価の有無は再開ごとに指定し直す（再開で前回の故障注入を繰り返さない）
        sf.query(
            conn,
            f"UPDATE {runs} SET status = 'QUEUED', ended_at = NULL, "
            "config = OBJECT_INSERT(OBJECT_INSERT(config, 'fail', PARSE_JSON(%s), TRUE), 'eval', %s, TRUE) "
            "WHERE run_id = %s",
            (json.dumps(fail), evaluate, run_id),
        )
    else:
        if from_step:
            raise OpsError(
                "--from は既存の run の再実行に使う（--resume <run_id> と一緒に指定する）"
            )
        sf.query(
            conn,
            f"INSERT INTO {runs} (run_id, corpus, slice, docs, config, image_tag, status) "
            "SELECT %s, %s, NULL, PARSE_JSON(%s), PARSE_JSON(%s), %s, 'QUEUED'",
            (run_id, corpus, json.dumps(pdf_ids), json.dumps(cfg, ensure_ascii=False), tag),
        )
    conf = json.dumps({"run_id": run_id, "skip_eval": not evaluate})
    sf.query(conn, f"EXECUTE TASK {v['db']}.{v['schema_ops']}.T_S00 USING CONFIG = $${conf}$$")


FROM_STEPS = ("A", "P", "E")


def prepare_from(conn, run_id: str, pdf_ids: list[str], step: str, tag: str) -> dict:
    """--from：指定した段以降をやり直すため、その段以降の成功の記録を消す（前段の成果物を確かめてから）。

    A：段 A（pdoc）から。A・P の記録を消す。
    P：段 K〜R から。全 PDF の段 A が同じイメージで成功していること。P の記録を消す（pdoc は作り直さない）。
    E：評価だけ。全 PDF の P が成功していること。予測の記録は消さない（--eval と一緒に使う）。
    S00・S30・S20 の記録は起動のたびに上書きされる。
    """
    if step not in FROM_STEPS:
        raise OpsError(f"--from は {' | '.join(FROM_STEPS)} のどれか: {step!r}")
    st = sf.fq("schema_ops", "STEP_RUNS")
    rows = sf.query(
        conn,
        f"SELECT step, doc_id, status, image_tag, output_uri FROM {st} WHERE run_id = %s",
        (run_id,),
    )
    by = {(r["step"], r["doc_id"]): r for r in rows}
    need = {"P": "A", "E": "P"}.get(step)
    if need:
        bad = [
            p
            for p in pdf_ids
            if (by.get((need, p)) or {}).get("status") != "SUCCEEDED"
            or (need == "A" and not (by.get((need, p)) or {}).get("output_uri"))
            or (by.get((need, p)) or {}).get("image_tag") != tag
        ]
        if bad:
            raise OpsError(
                f"--from {step}: 前の段 {need} の成果物が無いか、版が違う PDF がある: {bad[:5]}"
                f"（--from {'A' if need == 'A' else 'P'} からやり直す）"
            )
    clear = {"A": ("A", "P"), "P": ("P",), "E": ()}[step]
    for s_ in clear:
        sf.query(conn, f"DELETE FROM {st} WHERE run_id = %s AND step = %s", (run_id, s_))
    return {"cleared": list(clear)}


def run_status(conn, run_id: str) -> dict:
    run = sf.query(
        conn,
        f"SELECT status, message FROM {sf.fq('schema_ops', 'RUNS')} WHERE run_id = %s",
        (run_id,),
    )
    steps = sf.query(
        conn,
        f"SELECT step, doc_id, status, n_errors, error_text FROM {sf.fq('schema_ops', 'STEP_RUNS')} "
        "WHERE run_id = %s ORDER BY step, doc_id",
        (run_id,),
    )
    return {"run": run[0] if run else None, "steps": steps}


# Task の時間制限（sql/tasks/dag.sql の USER_TASK_TIMEOUT_MS。試験で一致を確かめる）。手元の待ちの上限は
# この合計に余裕を足した値にする（待ちが Task より先に切れると、動いているジョブを「終わらない」と報告するため）
TASK_TIMEOUT_MS = {
    "T_S00": 600000,
    "T_S10": 14400000,
    "T_S20": 7200000,
    "T_S30": 600000,
    "T_FINALIZE": 600000,
}
WAIT_TIMEOUT_S = sum(TASK_TIMEOUT_MS.values()) // 1000 + 600


def wait_run(conn, run_id: str, *, timeout_s: int = WAIT_TIMEOUT_S, poll_s: int = 20) -> dict:
    """RUNS の状態が終わり（SUCCEEDED・INCOMPLETE・FAILED）になるまで待つ。自分の台帳だけを見る。"""
    t0 = time.monotonic()
    while True:
        st = run_status(conn, run_id)
        s = (st["run"] or {}).get("status")
        if s in ("SUCCEEDED", "INCOMPLETE", "FAILED"):
            return st
        if time.monotonic() - t0 > timeout_s:
            raise OpsError(f"run が {timeout_s} 秒で終わらない: {run_id}（状態 {s}）")
        time.sleep(poll_s)


def ai_summary(conn, run_id: str) -> dict:
    """run の AI の要求数・この run で新しく呼んだ数・キャッシュの総数（自分の台帳だけを見る）。"""
    req = sf.fq("schema_work", "AI_REQUESTS")
    cache = sf.fq("schema_work", "AI_CACHE")
    r = sf.query(
        conn,
        f"SELECT (SELECT COUNT(DISTINCT cache_key) FROM {req} WHERE run_id = %s) AS n_requests, "
        f"(SELECT COUNT(*) FROM {cache} WHERE run_id = %s) AS n_called, "
        f"(SELECT COUNT(*) FROM {cache} WHERE err IS NULL) AS n_cache",
        (run_id, run_id),
    )[0]
    return {k: int(v or 0) for k, v in r.items()}


def ai_signature() -> dict[str, str]:
    """モデルとプロンプト一式の版（プロンプトのファイルの SHA-256）。変わった後の初回は課金の宣言が要る。"""
    import hashlib

    from .config import load_pipeline_config

    h = hashlib.sha256()
    for f in sorted((HOME / "configs" / "prompts").glob("*.txt")):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return {"model": load_pipeline_config().llm.model, "prompt_sig": h.hexdigest()[:16]}


def signature_seen(conn, sig: dict[str, str]) -> bool:
    """同じモデル・プロンプトの版で成功した run があるか。"""
    r = sf.query(
        conn,
        f"SELECT COUNT(*) AS n FROM {sf.fq('schema_ops', 'RUNS')} WHERE status = 'SUCCEEDED' "
        "AND config:model::STRING = %s AND config:prompt_sig::STRING = %s",
        (sig["model"], sig["prompt_sig"]),
    )
    return int(r[0]["n"]) > 0


def run_exists(conn, run_id: str) -> bool:
    q = f"SELECT COUNT(*) AS n FROM {sf.fq('schema_ops', 'RUNS')} WHERE run_id = %s"
    return int(sf.query(conn, q, (run_id,))[0]["n"]) > 0


# まだ終わっていないジョブの状態（SHOW JOB SERVICES の status）
_ACTIVE_JOB = ("PENDING", "RUNNING", "CANCELLING")


def active_jobs(conn, run_id: str) -> list[str]:
    """その run の予測ジョブのうち、まだ動いているもの。

    S10 はジョブの開始時に JOBS に RUNNING を書き、終わったら書き換える。Task の時間制限で呼び出しが
    切られると RUNNING のまま残り、ジョブそのものが動き続けているかは記録からは分からないので、
    SHOW JOB SERVICES の状態で確かめる（再開で同じ run のジョブを 2 つ動かさないため）。
    """
    rows = sf.query(
        conn,
        f"SELECT job_name FROM {sf.fq('schema_ops', 'JOBS')} WHERE run_id = %s AND status = 'RUNNING'",
        (run_id,),
    )
    names = {str(r["job_name"]).split(".")[-1].upper() for r in rows}
    if not names:
        return []
    n = sf.names()
    shows = sf.query(
        conn, f"SHOW JOB SERVICES LIKE 'JOB_PREDICT_%' IN SCHEMA {n.db}.{n.schema_ops}"
    )
    return sorted(
        r["name"]
        for r in shows
        if str(r["name"]).upper() in names and r.get("status") in _ACTIVE_JOB
    )


def needs_declaration(
    *,
    n_pdfs: int,
    n_pilot: int,
    no_cache: bool,
    n_cache: int,
    holdout: bool,
    new_signature: bool = False,
) -> list[str]:
    """課金の宣言が要る理由（空なら不要）。"""
    why = []
    if new_signature:
        why.append("モデルかプロンプトの版が変わった後の初回")
    if no_cache:
        why.append("--no-cache")
    if holdout:
        why.append("HOLDOUT を含む")
    if n_cache == 0:
        why.append("AI のキャッシュが空")
    if n_pdfs > n_pilot:
        why.append(f"対象 {n_pdfs} PDF が pilot（{n_pilot}）を超える")
    return why


# ---- teardown（名前は configs/deploy.env からだけ組み立てる。SHOW の結果やワイルドカードから DROP を作らない）


def teardown_plan(v: dict[str, str], *, keep_eval: bool) -> list[str]:
    """DROP の文の一覧（ACCOUNTADMIN で実行する）。keep_eval は評価 DB・評価ロール・管理ロール・ウェアハウスを残す。"""
    stmts = [
        "USE ROLE ACCOUNTADMIN",
        # Task グラフを止めてから消す（ルートを止めると子の Task も起動されない）
        f"ALTER TASK IF EXISTS {v['db']}.{v['schema_ops']}.T_S00 SUSPEND",
        f"ALTER COMPUTE POOL IF EXISTS {v['compute_pool']} STOP ALL",
        # 予測 DB を落とすと Task・プロシージャ・ステージ・イメージリポジトリ・予測ジョブも消える
        f"DROP DATABASE IF EXISTS {v['db']}",
    ]
    if not keep_eval:
        stmts += [f"DROP DATABASE IF EXISTS {v['eval_db']}"]
    stmts += [f"DROP COMPUTE POOL IF EXISTS {v['compute_pool']}"]
    if not keep_eval:
        stmts += [f"DROP WAREHOUSE IF EXISTS {v['warehouse']}"]
    stmts += [f"DROP ROLE IF EXISTS {v['role_predict']}"]
    if not keep_eval:
        stmts += [f"DROP ROLE IF EXISTS {v['role_eval']}", f"DROP ROLE IF EXISTS {v['role_admin']}"]
    return stmts


def applicable(plan: list[str], v: dict[str, str], db_exists: bool) -> list[str]:
    """実行する文。予測 DB が無いときは、DB の中の Task を止める文を除く。

    `ALTER TASK IF EXISTS <db>.<schema>.<task>` は、DB そのものが無いと IF EXISTS でもエラーになる。
    ほかの文はアカウントのオブジェクトの IF EXISTS なので、消す物が無くても通る（teardown を何回でも流せる）。
    """
    if db_exists:
        return list(plan)
    return [x for x in plan if not x.startswith(f"ALTER TASK IF EXISTS {v['db']}.")]


def db_exists(conn, name: str) -> bool:
    """DB があるか（名前の完全一致）。"""
    rows = sf.query(conn, f"SHOW DATABASES LIKE '{name}'")
    return any((r.get("name") or "").upper() == name.upper() for r in rows)


def eval_job_services(conn, v: dict[str, str]) -> list[str]:
    """評価 DB に残る評価ジョブの名前（台帳 EVAL_JOBS から。--keep-eval でプールを落とす前に消す）。"""
    try:
        rows = sf.query(
            conn, f"SELECT DISTINCT job_name FROM {v['eval_db']}.{v['schema_results']}.EVAL_JOBS"
        )
    except Exception:  # noqa: BLE001  評価 DB が無ければ空
        return []
    ok = re.compile(
        rf"^{re.escape(v['eval_db'])}\.{re.escape(v['schema_results'])}\.JOB_EVAL_[0-9]+$"
    )
    return [r["job_name"] for r in rows if r["job_name"] and ok.match(r["job_name"])]


def residue(conn, v: dict[str, str], *, keep_eval: bool) -> list[str]:
    """残っている専用オブジェクト（名前の完全一致で確かめる）。"""
    want = {
        "DATABASES": [v["db"]] + ([] if keep_eval else [v["eval_db"]]),
        "WAREHOUSES": [] if keep_eval else [v["warehouse"]],
        "COMPUTE POOLS": [v["compute_pool"]],
        "ROLES": [v["role_predict"]] + ([] if keep_eval else [v["role_eval"], v["role_admin"]]),
    }
    left = []
    for kind, names in want.items():
        for n in names:
            rows = sf.query(conn, f"SHOW {kind} LIKE '{n}'")
            if any(r.get("name") == n for r in rows):
                left.append(f"{kind}:{n}")
    return left

"""運用（故障注入・段 A の飛ばし・--from・課金の宣言・teardown・スクリプトの引数）の試験。Snowflake に接続しない。"""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from jpcalc import jobs, ops
from jpcalc.common.paths import HOME

REV = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 台帳の revision は 40 桁の SHA（jobs._check_run_values）


class Conn:
    """sf.query の cursor を偽る。SQL の断片で応答を返し、実行した SQL と引数を残す。"""

    def __init__(self, run=None, steps=(), eval_jobs=(), shows=()):
        self.run, self.steps, self.eval_jobs, self.shows = (
            run,
            list(steps),
            list(eval_jobs),
            set(shows),
        )
        self.sql: list[tuple[str, object]] = []

    def cursor(self):
        c = self

        class Cur:
            description = None
            rows: list = []

            def execute(self, sql, params=None):
                c.sql.append((sql, params))
                self.description, self.rows = None, []
                if "SELECT corpus, docs, config FROM" in sql:
                    r = c.run
                    self.description = [("CORPUS",), ("DOCS",), ("CONFIG",)]
                    self.rows = [(r["corpus"], json.dumps(r["docs"]), json.dumps(r["config"]))]
                elif "SELECT doc_id FROM" in sql and "STEP_RUNS" in sql:
                    step = params[1]
                    self.description = [("DOC_ID",)]
                    self.rows = [
                        (d,) for s, d, st, *_ in c.steps if s == step and st == "SUCCEEDED"
                    ]
                elif "SELECT step, doc_id, status, image_tag, output_uri" in sql:
                    self.description = [
                        (x,) for x in ("STEP", "DOC_ID", "STATUS", "IMAGE_TAG", "OUTPUT_URI")
                    ]
                    self.rows = [tuple(s) for s in c.steps]
                elif "SELECT DISTINCT job_name" in sql:
                    self.description = [("JOB_NAME",)]
                    self.rows = [(j,) for j in c.eval_jobs]
                elif sql.startswith("SHOW "):
                    name = sql.split("'")[1]
                    self.description = [("name",)]
                    self.rows = [(name,)] if name in c.shows else []

            def fetchall(self):
                return self.rows

            def close(self):
                pass

        return Cur()

    def recorded(self, step):
        """sf.record で書いた (doc_id, status, error_text)。"""
        out = []
        for sql, p in self.sql:
            if "MERGE INTO" in sql and isinstance(p, dict) and p.get("step") == step:
                out.append((p["doc_id"], p["status"], p.get("error_text")))
        return out


def _stage(tmp_path, pdfs):
    base = tmp_path / "pdfs" / "yakkan" / REV
    base.mkdir(parents=True)
    sha = {}
    for p in pdfs:
        b = f"%PDF {p}".encode()
        (base / f"{p}.pdf").write_bytes(b)
        sha[p] = {"sha256": hashlib.sha256(b).hexdigest()}
    (base / "pdf_sha256.json").write_text(json.dumps(sha))
    return tmp_path / "pdfs"


@pytest.fixture
def fake_pipeline(monkeypatch, tmp_path):
    """段 A と P を偽る（読み取りと AI を呼ばない）。P に渡った PDF を記録する。"""
    from jpcalc.pdfread import pdoc
    from jpcalc.predict import pipeline

    seen = {"built": [], "p": None}
    monkeypatch.setattr(jobs, "PDF_ROOT", _stage(tmp_path, ["d-1--s", "d-2--s"]))
    monkeypatch.setattr(jobs, "RESULTS_ROOT", tmp_path / "results")

    def build(pid, path):
        seen["built"].append(pid)
        return {"pdoc": {"read_errors": []}}

    def run_pdfs(conn, run_id, corpus, rev, ids, **kw):
        seen["p"] = list(ids)
        return {}

    monkeypatch.setattr(pdoc, "build", build)
    monkeypatch.setattr(pipeline, "run_pdfs", run_pdfs)
    monkeypatch.delenv("JPCALC_CACHE_SALT", raising=False)
    return seen


RUN = {
    "corpus": "yakkan",
    "docs": ["d-1--s", "d-2--s"],
    "config": {"revision": REV, "shots": False},
}


def test_fault_injection_at_p(fake_pipeline):
    run = json.loads(json.dumps(RUN))
    run["config"]["fail"] = {"step": "P", "pdf": "d-2--s"}
    c = Conn(run)
    out = jobs.run_predict("r1", conn=c)
    assert fake_pipeline["p"] == ["d-1--s"] and out["n_failed_injected"] == 1
    assert ("d-2--s", "FAILED", "故障注入（P）") in c.recorded("P")


def test_fault_injection_at_a_skips_p(fake_pipeline):
    run = json.loads(json.dumps(RUN))
    run["config"]["fail"] = {"step": "A", "pdf": "d-1--s"}
    c = Conn(run)
    jobs.run_predict("r1", conn=c)
    assert fake_pipeline["built"] == ["d-2--s"] and fake_pipeline["p"] == ["d-2--s"]
    assert ("d-1--s", "FAILED", "故障注入（A）") in c.recorded("A")


def test_resume_skips_succeeded_a_with_pdoc(fake_pipeline, tmp_path):
    pd = tmp_path / "results" / "yakkan" / REV / "pdoc"
    pd.mkdir(parents=True)
    (pd / "d-1--s.json").write_text("{}")
    c = Conn(RUN, steps=[("A", "d-1--s", "SUCCEEDED", None, "x")])
    jobs.run_predict("r1", conn=c)
    assert fake_pipeline["built"] == ["d-2--s"]  # 段 A は成功済みで pdoc がある PDF を作り直さない
    assert fake_pipeline["p"] == ["d-1--s", "d-2--s"]


def test_no_cache_sets_salt(fake_pipeline, monkeypatch):
    import os

    run = json.loads(json.dumps(RUN))
    run["config"]["no_cache"] = True
    jobs.run_predict("r-nc", conn=Conn(run))
    assert os.environ.get("JPCALC_CACHE_SALT") == "r-nc"
    monkeypatch.delenv("JPCALC_CACHE_SALT")


# ---- --from


def _steps(a_status="SUCCEEDED", p_status="SUCCEEDED", tag="20260101000000"):
    return [("A", p, a_status, tag, "uri") for p in ("x--a", "x--b")] + [
        ("P", p, p_status, tag, None) for p in ("x--a", "x--b")
    ]


def _deletes(c):
    return [p[1] for s, p in c.sql if s.startswith("DELETE FROM")]


def test_from_p_needs_a_and_clears_p():
    c = Conn(steps=_steps())
    assert ops.prepare_from(c, "r", ["x--a", "x--b"], "P", "20260101000000") == {"cleared": ["P"]}
    assert _deletes(c) == ["P"]


def test_from_p_refuses_without_a_or_with_other_image():
    with pytest.raises(ops.OpsError, match="前の段 A"):
        ops.prepare_from(
            Conn(steps=_steps(a_status="FAILED")), "r", ["x--a"], "P", "20260101000000"
        )
    with pytest.raises(ops.OpsError, match="版が違う"):
        ops.prepare_from(Conn(steps=_steps()), "r", ["x--a"], "P", "20269999999999")


def test_from_a_clears_a_and_p_and_from_e_clears_nothing():
    c = Conn(steps=[])
    ops.prepare_from(c, "r", ["x--a"], "A", "t")
    assert _deletes(c) == ["A", "P"]
    c = Conn(steps=_steps())
    ops.prepare_from(c, "r", ["x--a", "x--b"], "E", "20260101000000")
    assert _deletes(c) == []
    with pytest.raises(ops.OpsError):
        ops.prepare_from(
            Conn(steps=_steps(p_status="FAILED")), "r", ["x--a"], "E", "20260101000000"
        )


def test_from_rejects_unknown_step():
    with pytest.raises(ops.OpsError):
        ops.prepare_from(Conn(), "r", ["x"], "K", "t")


# ---- 課金の宣言


def test_needs_declaration():
    base = {"n_pdfs": 1, "n_pilot": 4, "no_cache": False, "n_cache": 10, "holdout": False}
    assert ops.needs_declaration(**base) == []
    assert ops.needs_declaration(**(base | {"n_cache": 0})) == ["AI のキャッシュが空"]
    assert (
        len(ops.needs_declaration(**(base | {"no_cache": True, "holdout": True, "n_pdfs": 5}))) == 3
    )


# ---- teardown


def test_teardown_plan_uses_explicit_names_only():
    v = ops.deploy_values()
    full = ops.teardown_plan(v, keep_eval=False)
    text = " ".join(full)
    assert "LIKE" not in text and "*" not in text and "%" not in text
    drops = [x.split()[-1] for x in full if x.startswith("DROP")]
    assert set(drops) == {
        v["db"], v["eval_db"], v["compute_pool"], v["warehouse"], v["role_predict"], v["role_eval"], v["role_admin"],
    }  # fmt: skip
    assert all(d.startswith("JA_DOC_CALC_") for d in drops)
    keep = " ".join(ops.teardown_plan(v, keep_eval=True))
    assert v["eval_db"] not in keep and v["role_eval"] not in keep and v["warehouse"] not in keep


def test_eval_job_services_only_own_names():
    v = ops.deploy_values()
    good = f"{v['eval_db']}.{v['schema_results']}.JOB_EVAL_20261019003026123"
    c = Conn(eval_jobs=[good, "OTHER_DB.X.JOB_EVAL_1", f"{good}; DROP DATABASE X"])
    assert ops.eval_job_services(c, v) == [good]


def test_residue_matches_exact_names():
    v = ops.deploy_values()
    c = Conn(shows={v["compute_pool"]})
    assert ops.residue(c, v, keep_eval=False) == [f"COMPUTE POOLS:{v['compute_pool']}"]


# ---- スクリプト（Snowflake に接続しない経路だけ）


def _sh(*args):
    return subprocess.run(["bash", *args], cwd=HOME, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("script", ["setup.sh", "start.sh", "teardown.sh"])
def test_scripts_help_and_strict_mode(script):
    p = HOME / "scripts" / script
    assert "set -euo pipefail" in p.read_text(encoding="utf-8")
    assert _sh(str(p), "--help").returncode == 0


@pytest.mark.parametrize(
    "args,msg",
    [
        (["--corpus", "yakkan", "--slice", "pilot", "--input", "json", "--cards", "auto"], "--input は pdf"),
        (["--corpus", "yakkan", "--slice", "pilot", "--input", "pdf", "--cards", "given"], "--cards は auto"),
        (["--corpus", "yakkan", "--slice", "pilot", "--docs", "a", "--input", "pdf", "--cards", "auto"], "1 つだけ"),
        (["--corpus", "yakkan", "--slice", "pilot", "--input", "pdf", "--cards", "auto", "--from", "P"], "--resume"),
    ],
)  # fmt: skip
def test_start_rejects_bad_args(args, msg):
    r = _sh(str(HOME / "scripts" / "start.sh"), *args)
    assert r.returncode != 0 and msg in r.stderr


def test_new_signature_needs_declaration_and_signature_is_stable():
    base = {"n_pdfs": 1, "n_pilot": 4, "no_cache": False, "n_cache": 10, "holdout": False}
    assert ops.needs_declaration(**base, new_signature=True) == [
        "モデルかプロンプトの版が変わった後の初回"
    ]
    a, b = ops.ai_signature(), ops.ai_signature()
    assert a == b and set(a) == {"model", "prompt_sig"} and len(a["prompt_sig"]) == 16


def test_from_p_refuses_unknown_image_of_previous_step():
    steps = [("A", "x--a", "SUCCEEDED", None, "uri")]
    with pytest.raises(ops.OpsError, match="版が違う"):
        ops.prepare_from(Conn(steps=steps), "r", ["x--a"], "P", "20260101000000")


def test_teardown_suspends_tasks_first():
    plan = ops.teardown_plan(ops.deploy_values(), keep_eval=False)
    i_suspend = next(i for i, x in enumerate(plan) if "T_S00 SUSPEND" in x)
    i_drop = next(i for i, x in enumerate(plan) if x.startswith("DROP"))
    assert i_suspend < i_drop


def test_teardown_skips_task_suspend_without_database():
    """予測 DB が無いと ALTER TASK IF EXISTS <db>.… はエラーになるので、その文だけを除く（teardown を何回でも流せる）。"""
    v = ops.deploy_values()
    plan = ops.teardown_plan(v, keep_eval=False)
    assert ops.applicable(plan, v, True) == plan
    rest = ops.applicable(plan, v, False)
    assert not any(x.startswith("ALTER TASK") for x in rest)
    assert [x for x in plan if not x.startswith("ALTER TASK")] == rest

    class Conn:
        def __init__(self, names):
            self.names = names

        def cursor(self):
            names = self.names

            class C:
                description = [("name",)]

                def execute(self, sql, params=None):
                    self.rows = [(n,) for n in names]

                def fetchall(self):
                    return self.rows

                def close(self):
                    pass

            return C()

    assert ops.db_exists(Conn([v["db"]]), v["db"]) is True
    assert ops.db_exists(Conn([]), v["db"]) is False


def test_start_rejects_run_id_with_resume():
    r = _sh(
        str(HOME / "scripts" / "start.sh"),
        *[
            "--corpus",
            "yakkan",
            "--slice",
            "pilot",
            "--input",
            "pdf",
            "--cards",
            "auto",
            "--resume",
            "r1",
            "--run-id",
            "r2",
        ],
    )
    assert r.returncode != 0 and "一緒に指定しない" in r.stderr


# ---- モデルの確認（check-model）


def _fake_query(answers):
    """sf.query を偽る。SQL の先頭の語で応答（例外か行）を返し、実行した SQL を残す。"""
    seen = []

    def q(conn, sql, params=None):
        seen.append(sql)
        for head, ans in answers.items():
            if sql.lstrip().upper().startswith(head):
                if isinstance(ans, Exception):
                    raise ans
                return ans
        return []

    return q, seen


def test_check_model_ok(monkeypatch):
    q, seen = _fake_query({"SELECT AI_COMPLETE": [{"r": "OK"}]})
    monkeypatch.setattr(ops.sf, "query", q)
    r = ops.check_model(object(), "claude-sonnet-5")
    assert r["ok"] is True and len(seen) == 1 and "'claude-sonnet-5'" in seen[0]


def test_check_model_unavailable_reports_cross_region(monkeypatch):
    q, seen = _fake_query(
        {
            "SELECT AI_COMPLETE": RuntimeError("Model unavailable in your region\nmore"),
            "SHOW PARAMETERS": [{"key": "CORTEX_ENABLED_CROSS_REGION", "value": "AWS_JP"}],
        }
    )
    monkeypatch.setattr(ops.sf, "query", q)
    r = ops.check_model(object(), "claude-sonnet-5")
    assert r == {
        "ok": False,
        "model": "claude-sonnet-5",
        "error": "Model unavailable in your region",
        "cross_region": "AWS_JP",
    }
    assert not any(s.upper().startswith("ALTER") for s in seen)  # アカウントの設定は変えない


def test_check_model_parameter_unreadable(monkeypatch):
    q, _ = _fake_query(
        {"SELECT AI_COMPLETE": RuntimeError("x"), "SHOW PARAMETERS": RuntimeError("denied")}
    )
    monkeypatch.setattr(ops.sf, "query", q)
    r = ops.check_model(object(), "claude-sonnet-5")
    assert r["ok"] is False and r["cross_region"] is None


@pytest.mark.parametrize("bad", ["", "x'); DROP TABLE t; --", "Claude", "a b"])
def test_check_model_rejects_bad_model_names(monkeypatch, bad):
    q, seen = _fake_query({})
    monkeypatch.setattr(ops.sf, "query", q)
    with pytest.raises(ops.OpsError):
        ops.check_model(object(), bad)
    assert seen == []


def test_setup_checks_the_model_before_building():
    s = (HOME / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert s.index("jp check-model") < s.index("build_push.sh")
    assert s.index("jp verify-roles") < s.index("jp check-model")


# ---- HOLDOUT の許可は、HOLDOUT を検査するすべての段に渡す


def test_start_passes_allow_holdout_to_every_step_that_checks_it():
    """start.sh の targets・fetch・run は HOLDOUT を検査して止めるので、--allow-holdout を同じに渡す。"""
    from jpcalc.cli import build_parser

    p = build_parser()
    for argv in (
        ["targets", "--corpus", "yakkan", "--docs", "x", "--allow-holdout"],
        ["fetch", "--corpus", "yakkan", "--docs", "x", "--allow-holdout"],
        ["run", "--corpus", "yakkan", "--pdfs", "x", "--allow-holdout"],
    ):
        assert p.parse_args(argv).allow_holdout is True, argv[0]
    text = (HOME / "scripts" / "start.sh").read_text(encoding="utf-8").replace("\\\n", " ")
    # run の引数は run_args にまとめて渡す（--allow-holdout も run_args に足す）
    assert "run_args+=(--allow-holdout)" in text
    lines = [
        ln for ln in text.splitlines() if any(f"jp {c} " in ln for c in ("targets", "fetch", "run"))
    ]
    assert {c for c in ("targets", "fetch", "run") if any(f"jp {c} " in ln for ln in lines)} == {
        "targets",
        "fetch",
        "run",
    }
    for ln in lines:
        assert "holdout" in ln or "run_args" in ln, ln


# ---- 予測ジョブのまとまりごとの処理（Task の時間制限で切れても再開で進む）


def test_predict_job_processes_pdfs_in_chunks(monkeypatch, tmp_path):
    from jpcalc import config
    from jpcalc.pdfread import pdoc
    from jpcalc.predict import pipeline

    pdfs = [f"d-{i}--s" for i in range(1, 6)]
    monkeypatch.setattr(jobs, "PDF_ROOT", _stage(tmp_path, pdfs))
    monkeypatch.setattr(jobs, "RESULTS_ROOT", tmp_path / "results")
    monkeypatch.setattr(pdoc, "build", lambda pid, path: {"pdoc": {"read_errors": []}})
    calls = []

    def run_pdfs(conn, run_id, corpus, rev, ids, **kw):
        calls.append(list(ids))
        return {"_llm_stats": {"requests": len(ids), "called": 1}}

    monkeypatch.setattr(pipeline, "run_pdfs", run_pdfs)
    cfg = config.load_pipeline_config()
    small = cfg.model_copy(update={"run": cfg.run.model_copy(update={"chunk_pdfs": 2})})
    monkeypatch.setattr(config, "load_pipeline_config", lambda: small)
    run = {"corpus": "yakkan", "docs": pdfs, "config": {"revision": REV, "shots": False}}
    out = jobs.run_predict("r1", conn=Conn(run))
    assert calls == [pdfs[0:2], pdfs[2:4], pdfs[4:5]]
    assert out["llm"] == {"requests": 5, "called": 3}
    # 2 つ目のまとまりの途中で切れた後の再開：段 P が成功したまとまりは飛ばす
    calls.clear()
    done = [("P", p, "SUCCEEDED") for p in pdfs[0:2]] + [("A", p, "SUCCEEDED") for p in pdfs]
    jobs.run_predict("r1", conn=Conn(run, steps=done))
    assert calls == [pdfs[2:4], pdfs[4:5]]


def test_pipeline_config_has_the_chunk_size():
    from jpcalc.config import load_pipeline_config

    assert load_pipeline_config().run.chunk_pdfs == 4


def test_duration_note_warns_beyond_the_task_limit():
    from jpcalc.cli import _duration_note

    assert "時間制限" not in _duration_note(4)
    assert "約 46 分" in _duration_note(4)
    assert "時間制限（4 時間）を超える" in _duration_note(
        104
    ) and "10 PDF ほどずつ" in _duration_note(104)


# ---- 再開の前に、前の予測ジョブが動いていないかを確かめる


def _jobs_query(jobs_rows, shows):
    seen = []

    def q(conn, sql, params=None):
        seen.append(sql)
        if "FROM" in sql and ".JOBS" in sql:
            return jobs_rows
        if sql.startswith("SHOW JOB SERVICES"):
            return shows
        return []

    return q, seen


def test_active_jobs_reports_a_job_still_running(monkeypatch):
    q, _ = _jobs_query(
        [{"job_name": "DB.OPS.JOB_PREDICT_20261104010101000"}],
        [
            {"name": "JOB_PREDICT_20261104010101000", "status": "RUNNING"},
            {"name": "JOB_PREDICT_20261103010101000", "status": "RUNNING"},  # ほかの run のジョブ
        ],
    )
    monkeypatch.setattr(ops.sf, "query", q)
    assert ops.active_jobs(object(), "r1") == ["JOB_PREDICT_20261104010101000"]


@pytest.mark.parametrize("status", ["DONE", "FAILED", "CANCELLED"])
def test_active_jobs_ignores_finished_jobs(monkeypatch, status):
    q, _ = _jobs_query(
        [{"job_name": "DB.OPS.JOB_PREDICT_1"}], [{"name": "JOB_PREDICT_1", "status": status}]
    )
    monkeypatch.setattr(ops.sf, "query", q)
    assert ops.active_jobs(object(), "r1") == []


def test_active_jobs_skips_show_when_no_job_is_recorded_running(monkeypatch):
    q, seen = _jobs_query([], [])
    monkeypatch.setattr(ops.sf, "query", q)
    assert ops.active_jobs(object(), "r1") == [] and not any(s.startswith("SHOW") for s in seen)


# ---- teardown の前の退避：評価ロールで入れないときは、評価 DB が無いときだけ「退避するものは無い」


def _export_args(**kw):
    import argparse

    return argparse.Namespace(all=True, run_id=None, dest=None, **kw)


def _no_eval_role(monkeypatch, *, eval_db_exists):
    from jpcalc import cli
    from jpcalc.common import sf

    def connect(role=None, **kw):
        if role == sf.names().role_eval:
            raise RuntimeError(
                "Role 'JA_DOC_CALC_EVAL_ROLE' specified does not exist or not authorized"
            )
        raise AssertionError("unexpected connect")

    monkeypatch.setattr(sf, "connect", connect)
    if isinstance(eval_db_exists, Exception):

        def boom():
            raise eval_db_exists

        monkeypatch.setattr(cli, "_eval_db_exists", boom)
    else:
        monkeypatch.setattr(cli, "_eval_db_exists", lambda: eval_db_exists)
    return cli


def test_export_stops_when_eval_db_exists_but_eval_role_cannot_connect(monkeypatch, capsys):
    cli = _no_eval_role(monkeypatch, eval_db_exists=True)
    assert cli._cmd_export_results(_export_args()) == 1
    err = capsys.readouterr().err
    assert "退避できないので消さない" in err and "--no-export" in err


def test_export_is_a_no_op_only_when_eval_db_is_gone(monkeypatch, capsys):
    cli = _no_eval_role(monkeypatch, eval_db_exists=False)
    assert cli._cmd_export_results(_export_args()) == 0
    assert "評価 DB が無いので" in capsys.readouterr().out


def test_export_stops_when_eval_db_existence_cannot_be_checked(monkeypatch):
    cli = _no_eval_role(monkeypatch, eval_db_exists=RuntimeError("network"))
    assert cli._cmd_export_results(_export_args()) == 1


def test_teardown_script_stops_before_dropping_when_export_fails():
    s = (HOME / "scripts" / "teardown.sh").read_text(encoding="utf-8")
    i_export, i_drop = s.index("jp export-results --all"), s.index("jp teardown --yes")
    assert i_export < i_drop and "|| die" in s[i_export:i_drop]


def test_wait_limit_covers_the_task_timeouts():
    """手元の待ちの上限は、Task の時間制限（dag.sql）の合計より長い。"""
    import re

    sql = (HOME / "sql" / "tasks" / "dag.sql").read_text(encoding="utf-8")
    got = dict(
        re.findall(
            r"TASK <% db %>\.<% schema_ops %>\.(T_\w+)\s+WAREHOUSE = <% warehouse %> USER_TASK_TIMEOUT_MS = (\d+)",
            sql,
        )
    )
    assert {k: int(v) for k, v in got.items()} == ops.TASK_TIMEOUT_MS
    assert sum(ops.TASK_TIMEOUT_MS.values()) < ops.WAIT_TIMEOUT_S * 1000
    import inspect

    assert inspect.signature(ops.wait_run).parameters["timeout_s"].default == ops.WAIT_TIMEOUT_S


def test_suggested_batch_fits_the_predict_job_limit():
    from jpcalc import cli

    assert cli._MIN_BASE + cli._MIN_PER_PDF * cli._BATCH_PDFS < cli._TASK_LIMIT_MIN / 2
    assert f"{cli._BATCH_PDFS} PDF ほどずつ" in cli._duration_note(104)


def test_push_failure_advice_reruns_setup():
    """push に失敗した後は setup を再実行する（build_push.sh だけでは手本の作成が抜ける）。"""
    bp = (HOME / "scripts" / "build_push.sh").read_text(encoding="utf-8")
    line = next(ln for ln in bp.splitlines() if "docker push に 3 回失敗した" in ln)
    assert "setup.sh --corpus yakkan --yes を再実行する" in line
    readme = (HOME / "README.md").read_text(encoding="utf-8")
    row = next(ln for ln in readme.splitlines() if "docker push に 3 回失敗した" in ln)
    assert "`scripts/setup.sh --corpus yakkan --yes` を再実行する" in row
    setup = (HOME / "scripts" / "setup.sh").read_text(encoding="utf-8")
    assert setup.index("build_push.sh") < setup.index("jp make-shots")

"""SPCS の予測ジョブの入口とアップロード・ロール検証の解析（Snowflake に接続しない）。"""

from __future__ import annotations

import hashlib
import json

import pytest

from jpcalc import jobs, ops
from jpcalc.common import sqltpl
from jpcalc.common.names import build_names

REV = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # 台帳の revision は 40 桁の SHA（jobs._check_run_values）


class FakeConn:
    """sf.query が呼ぶ cursor を偽る。SQL の頭で応答を返す。"""

    def __init__(self, runs, done=()):
        self.runs, self.done, self.sql = runs, set(done), []

    def cursor(self):
        return _Cur(self)


class _Cur:
    def __init__(self, c):
        self.c, self.description, self._rows = c, None, []

    def execute(self, sql, params=None):
        self.c.sql.append(sql)
        if "FROM" in sql and ".RUNS" in sql and "SELECT corpus" in sql:
            r = self.c.runs
            self.description = [("CORPUS",), ("DOCS",), ("CONFIG",)]
            self._rows = [(r["corpus"], json.dumps(r["docs"]), json.dumps(r["config"]))]
        elif "STEP_RUNS" in sql and "SELECT doc_id" in sql:
            self.description = [("DOC_ID",)]
            self._rows = [(d,) for d in self.c.done]
        else:
            self.description, self._rows = None, []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


RUN = {
    "corpus": "yakkan",
    "docs": ["d-1--s", "d-2--s"],
    "config": {"revision": REV, "shots": False},
}


def _stage(tmp_path, pdfs: dict[str, bytes], sha_override=None):
    base = tmp_path / "yakkan" / REV
    base.mkdir(parents=True)
    shas = {}
    for p, b in pdfs.items():
        (base / f"{p}.pdf").write_bytes(b)
        shas[p] = {"sha256": hashlib.sha256(b).hexdigest()}
    shas.update(sha_override or {})
    (base / "pdf_sha256.json").write_text(json.dumps(shas), encoding="utf-8")
    return tmp_path


def test_load_run_and_succeeded():
    c = FakeConn(RUN, done=["d-1--s"])
    rc = jobs.load_run(c, "run1")
    assert rc.pdf_ids == ["d-1--s", "d-2--s"] and rc.revision == REV and rc.use_shots is False
    assert jobs.succeeded(c, "run1") == {"d-1--s"}


def test_stage_pdfs_verifies_sha(tmp_path):
    root = _stage(tmp_path, {"d-1--s": b"%PDF-a", "d-2--s": b"%PDF-b"})
    rc = jobs.load_run(FakeConn(RUN), "run1")
    got = jobs.stage_pdfs(rc, root)
    assert set(got) == {"d-1--s", "d-2--s"}


def test_stage_pdfs_rejects_tampered(tmp_path):
    root = _stage(
        tmp_path, {"d-1--s": b"%PDF-a", "d-2--s": b"%PDF-b"}, {"d-2--s": {"sha256": "0" * 64}}
    )
    with pytest.raises(jobs.JobError, match="d-2--s"):
        jobs.stage_pdfs(jobs.load_run(FakeConn(RUN), "run1"), root)


def test_stage_pdfs_requires_sha_file(tmp_path):
    (tmp_path / "yakkan" / REV).mkdir(parents=True)
    with pytest.raises(jobs.JobError, match="pdf_sha256.json"):
        jobs.stage_pdfs(jobs.load_run(FakeConn(RUN), "run1"), tmp_path)


def test_all_succeeded_skips_without_touching_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "PDF_ROOT", tmp_path / "nothing")
    out = jobs.run_predict("run1", conn=FakeConn(RUN, done=["d-1--s", "d-2--s"]))
    assert out["skipped"] and out["n"] == 2


def test_job_spec_mounts_only_predict_stages():
    from jpcalc.common.paths import HOME

    spec = (HOME / "container" / "job_specs" / "predict.yaml").read_text(encoding="utf-8")
    assert "{{ stage_pdfs }}" in spec and "{{ stage_results }}" in spec
    for bad in ("gold", "GOLD", "eval", "EVAL", "sh -c", "external_access"):
        assert bad not in spec, bad


def test_parse_role_cases():
    v = sqltpl.variables(build_names("JA_DOC_CALC_"), warehouse_size="XSMALL")
    cases = ops.parse_cases(sqltpl.render_file(sqltpl.VERIFY_FILE, v))
    assert len(cases) >= 10 and {e for e, _ in cases} == {"ok", "fail"}
    # どのケースも副ロールを外してから実行する
    assert all("USE SECONDARY ROLES NONE" in line for _, line in cases)
    # 予測ロールが評価 DB に触れるケースはすべて fail を期待する
    for e, line in cases:
        if line.startswith("USE ROLE JA_DOC_CALC_PREDICT") and "JA_DOC_CALC_EVAL_DB" in line:
            assert e == "fail", line


def test_run_id_and_tag_rules():
    assert ops.RUN_ID.match("yakkan-1a2b3c4d") and not ops.RUN_ID.match("x'; DROP")
    assert ops.TAG.match("20261019123456") and not ops.TAG.match("latest")


def test_put_rejects_quote_in_path(tmp_path):
    with pytest.raises(ops.OpsError):
        ops._put(None, tmp_path / "a'b.pdf", "@X.Y.Z/")


def test_dockerignore_excludes_private():
    from jpcalc.common.paths import HOME

    text = (HOME / ".dockerignore").read_text(encoding="utf-8")
    for need in ("configs/deploy.local.env", "configs/shots/"):
        assert need in text
    assert text.splitlines()[1].strip() == "**"  # 許可リスト方式（既定は入れない）


@pytest.mark.parametrize(
    "field,value",
    [
        ("docs", ["../../gold/x"]),
        ("docs", ["d-1--s", "a/b"]),
        ("revision", "../r0"),
        ("revision", "main"),
        ("corpus", "../yakkan"),
    ],
)
def test_load_run_rejects_values_that_would_escape_the_stage(field, value):
    """台帳は予測側が書けるので、パスに入る値の形を確かめる（評価ジョブも load_run を使う）。"""
    run = json.loads(json.dumps(RUN))
    if field == "revision":
        run["config"]["revision"] = value
    else:
        run[field] = value
    with pytest.raises(jobs.JobError, match="形が正しくない"):
        jobs.load_run(FakeConn(run), "r1")


def test_dockerignore_excludes_every_gitignored_config():
    """configs/ の中で公開しないもの（.gitignore の対象）は、イメージにも入れない（.dockerignore で除く）。"""
    from jpcalc.common.paths import HOME

    git = [
        ln.strip()
        for ln in (HOME / ".gitignore").read_text(encoding="utf-8").splitlines()
        if ln.strip().startswith("configs/")
    ]
    docker = {
        ln.strip() for ln in (HOME / ".dockerignore").read_text(encoding="utf-8").splitlines()
    }
    assert git and not [g for g in git if g not in docker]
    bp = (HOME / "scripts" / "build_push.sh").read_text(encoding="utf-8")
    for path in (
        "/app/configs/opt",
        "/app/configs/opt_*.yaml",
        "/app/configs/prompts/k_cards_contract_p*.txt",
    ):
        assert path in bp  # build の後にイメージの中で無いことを確かめる

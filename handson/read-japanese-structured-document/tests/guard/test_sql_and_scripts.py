"""SQL・ジョブ仕様・シェルの静的検査（既知の罠と厳守事項を、Snowflake を使わずに確かめる）。"""

from __future__ import annotations

import re
import subprocess

import pytest
import yaml

from jpdocread.common.paths import HOME

SQL = HOME / "sql"
SCRIPTS = HOME / "scripts"
SPEC = HOME / "container" / "job_specs" / "predict.yaml"


def _sql_files() -> list:
    return sorted(SQL.rglob("*.sql"))


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: str(p.relative_to(HOME)))
def test_user_exceptions_are_minus_20001_or_above(path):
    codes = [
        int(c) for c in re.findall(r"EXCEPTION\s*\(\s*(-\d+)", path.read_text(encoding="utf-8"))
    ]
    assert all(-20999 <= c <= -20001 for c in codes), codes


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: str(p.relative_to(HOME)))
def test_no_lateral_flatten_left_of_join(path):
    """`FROM x, LATERAL FLATTEN(...) v JOIN y` は失敗する（移植元 F20）。FLATTEN は CTE に持ち上げる。"""
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    assert not re.search(
        r"LATERAL\s+FLATTEN\s*\([^)]*\)\s*\w*\s+(LEFT\s+|INNER\s+)?JOIN\b", text, re.I
    )


@pytest.mark.parametrize(
    "path",
    [p for p in sorted((SQL / "procedures").glob("*.sql")) if p.name != "s60_evaluate.sql"],
    ids=lambda p: p.name,
)
def test_procedures_run_as_predict_without_secondary_roles(path):
    head = path.read_text(encoding="utf-8")
    assert "USE ROLE <% role_predict %>;" in head and "USE SECONDARY ROLES NONE;" in head


@pytest.mark.parametrize("path", _sql_files(), ids=lambda p: str(p.relative_to(HOME)))
def test_no_or_replace_on_data_objects(path):
    """`CREATE OR REPLACE` はコード（プロシージャ・関数・Task・ビュー）とプロシージャ内の一時表だけ（データを消さない）。"""
    bad = re.findall(
        r"CREATE\s+OR\s+REPLACE\s+(?!PROCEDURE|FUNCTION|TASK|VIEW|TEMPORARY\s+TABLE)(\w+)",
        path.read_text(encoding="utf-8"),
        re.I,
    )
    assert bad == []


def test_role_checks_pair_every_fail_with_an_ok_on_the_same_object():
    """fail を期待するケースには、同じ対象を別のロールで読める ok のケースがある（偽の合格を防ぐ）。"""
    text = (SQL / "verify" / "roles.sql").read_text(encoding="utf-8")
    cases = re.findall(r"-- expect: (ok|fail)\n(USE ROLE <% (\w+) %>;[^\n]*)", text)
    assert cases and all("USE SECONDARY ROLES NONE" in line for _, line, _ in cases)

    def target(line: str) -> str:
        return re.sub(r"^.*?(FROM|LIST|REMOVE)\s+", "", line).rstrip(";")

    oks = {target(line) for exp, line, _ in cases if exp == "ok"}
    fails = [target(line) for exp, line, _ in cases if exp == "fail"]
    assert fails and all(t in oks for t in fails), [t for t in fails if t not in oks]


def test_job_spec_does_not_wrap_command_in_a_shell():
    spec = yaml.safe_load(
        SPEC.read_text(encoding="utf-8").replace("{{", "'{{").replace("}}", "}}'")
    )
    c = spec["spec"]["containers"][0]
    assert c["command"][:3] == ["python", "-m", "jpdocread"]
    assert not any(x in ("sh", "bash", "-c") for x in c["command"])


def test_job_spec_stage_volumes_use_uid_1000_and_whole_scalar_variables():
    text = SPEC.read_text(encoding="utf-8")
    spec = yaml.safe_load(text.replace("{{", "'{{").replace("}}", "}}'"))
    vols = spec["spec"]["volumes"]
    assert vols and all(
        v["source"] == "stage" and v["uid"] == 1000 and v["gid"] == 1000 for v in vols
    )
    # 値の一部だけを置き換えない（USING の値は JSON リテラルとして差し込まれる）
    assert not re.search(r"\S\{\{|\}\}\S", text)


@pytest.mark.parametrize(
    "spec_name, proc_file, proc_name",
    [
        ("predict.yaml", "steps.sql", "RUN_JOB"),
        ("evaluate.yaml", "s60_evaluate.sql", "S60_EVALUATE"),
    ],
)
def test_job_launcher_passes_every_template_variable(spec_name, proc_file, proc_name):
    spec = SPEC.parent / spec_name
    used = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", spec.read_text(encoding="utf-8")))
    proc = (SQL / "procedures" / proc_file).read_text(encoding="utf-8")
    body = proc[proc.index(f"PROCEDURE <% db %>.<% schema_ops %>.{proc_name}") :]
    body = body[: body.index("$$;")]
    passed = set(re.findall(r"(\w+) => ''", body))
    assert used == passed, (used - passed, passed - used)


def test_evaluate_job_does_not_mount_prediction_inputs():
    """評価ジョブは正解と読み取り結果だけをマウントする（予測側の入力・作業域・キャッシュに触れない）。"""
    text = (SPEC.parent / "evaluate.yaml").read_text(encoding="utf-8")
    assert "stage_docs" not in text and "stage_work" not in text
    proc = (SQL / "procedures" / "s60_evaluate.sql").read_text(encoding="utf-8")
    assert "USE ROLE <% role_eval %>;" in proc and "<% schema_raw %>" not in proc


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.sh")), ids=lambda p: p.name)
def test_shell_scripts_parse_and_are_strict(path):
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0
    assert "set -euo pipefail" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.sh")), ids=lambda p: p.name)
def test_shell_scripts_take_connection_and_names_from_jpdocread(path):
    """接続名・DB 名をスクリプトに書かない。接頭辞の直書きも無い。"""
    text = path.read_text(encoding="utf-8")
    assert "JA_DOC_STRUCTURED_" not in text
    # snow の -c に渡すのは "$CONNECTION" だけ（接続名の直書きを形によらず拒む）
    vals = re.findall(r"\bsnow(?:_cli)?\s[^\n]*?\s-c\s+(\S+)", text)
    # 案内文のプレースホルダ（<接続名>）は許す
    assert all(v == '"$CONNECTION"' or re.fullmatch(r"<[^>]+>", v) for v in vals), vals


def test_build_push_never_uses_latest():
    text = (SCRIPTS / "build_push.sh").read_text(encoding="utf-8")
    assert ":latest" not in text and "!= latest" in text


@pytest.mark.parametrize("name", ["setup", "start", "teardown", "build_push", "verify_roles"])
def test_help_prints_only_the_header_and_exits_zero(name):
    # --help は副作用（接続・ビルド・SQL）の前に、先頭のコメントだけを表示して終わる
    script = SCRIPTS / f"{name}.sh"
    done = subprocess.run(
        ["bash", str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"{name}.sh") or done.stdout.startswith(f"scripts/{name}.sh")
    assert "set -euo pipefail" not in done.stdout
    assert "source " not in done.stdout

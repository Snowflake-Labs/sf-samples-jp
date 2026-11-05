"""正解漏れガード。リポジトリが通り、わざと違反したコードが落ちること（逆対照）。"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from jpcalc.common.guard import GuardRules, find_forbidden, run_guard
from jpcalc.config import load_guard_config


@pytest.fixture(scope="module")
def rules() -> GuardRules:
    return GuardRules.load()


def test_repo_passes(rules):
    res = run_guard(rules=rules)
    assert res.ok, res.violations
    assert res.modules > 0
    assert res.checks_run == ["no_eval_import", "no_dynamic_import", "no_gold_names"]


def _pkg(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "jpcalc"
    for pkg in ("fetch", "pdfread", "predict", "common", "eval"):
        (src / pkg).mkdir(parents=True, exist_ok=True)
        (src / pkg / "__init__.py").write_text("", encoding="utf-8")
    for rel, body in files.items():
        (src / rel).write_text(textwrap.dedent(body), encoding="utf-8")
    return src


@pytest.mark.parametrize(
    "code",
    [
        "import jpcalc.eval.match\n",
        "from jpcalc.eval import match\n",
        "from jpcalc import eval\n",
        "from ..eval import gold\n",
        "from .. import eval\n",
        "def f():\n    from ..eval.score import x\n",
        "from ..eval.read_score import score\n",
    ],
)
@pytest.mark.parametrize("where", ["predict/bad.py", "pdfread/bad.py"])
def test_eval_import_is_caught(tmp_path, rules, code, where):
    src = _pkg(tmp_path, {where: code})
    res = run_guard(src, rules)
    assert any("評価側を import" in v for v in res.violations), res.violations


def test_builtin_eval_name_is_not_import(tmp_path, rules):
    # 組み込みの eval や、eval を名前に含む別モジュールは import の違反ではない
    src = _pkg(tmp_path, {"predict/ok.py": "import evaluate_helpers\nx = 'evaluation'\n"})
    assert run_guard(src, rules).ok


def test_entry_module_allows_eval_only_in_named_function(tmp_path, rules):
    ok = "def _cmd_eval(a):\n    from .eval import evaluate\n"
    assert run_guard(_pkg(tmp_path, {"cli.py": ok}), rules).ok
    bad = "from .eval import evaluate\n"
    res = run_guard(_pkg(tmp_path / "b", {"cli.py": bad}), rules)
    assert any("モジュールの先頭" in v for v in res.violations)


@pytest.mark.parametrize(
    "literal",
    [
        "documents/{doc_id}/policy.json",
        "policy.json",
        "inputs/x/calendar.json",
        "answers/{cid}/spec.json",
        "calc/",
        "documents/x/calc/tests/test_calc.py",
        "calc",  # Path(root) / "calc"
        "answers",
        "views",
        "DOCUMENTS/X/POLICY.JSON",  # 大文字
        "answers\\x\\spec.json",  # Windows の区切り
        "jpcalc.eval",  # importlib に渡す文字列
        "x/pages/page-001.png",
        "tests/conftest.py",
        "views/pages.jsonl",
        "data/documents.jsonl",
        "index.json",
        "x/layout.json",
    ],
)
def test_gold_literal_is_caught(tmp_path, rules, literal):
    src = _pkg(tmp_path, {"fetch/bad.py": f"P = {literal!r}\n"})
    res = run_guard(src, rules)
    assert any("正解側の名前" in v for v in res.violations), (literal, res.violations)


@pytest.mark.parametrize(
    "literal",
    [
        "public_index.jsonl",  # index.json に前方一致するが別名
        "my_policy.json.bak2",  # 前に英字がある
        "tests",  # 語としての tests（パスでない）
        "pages",
        "documents/{doc_id}/{doc_id}--{style}/doc.pdf",
        "inputs/{doc_id}/{doc_id}--{style}.pdf",
        "out/pdoc.json",
    ],
)
def test_benign_literal_passes(tmp_path, rules, literal):
    src = _pkg(tmp_path, {"fetch/ok.py": f"P = {literal!r}\n"})
    assert run_guard(src, rules).ok, literal


def test_bytes_literal_is_caught(tmp_path, rules):
    src = _pkg(tmp_path, {"fetch/bad.py": "P = b'policy.json'\n"})
    assert not run_guard(src, rules).ok


@pytest.mark.parametrize(
    "code",
    [
        "import importlib\nm = importlib.import_module(name)\n",
        "from importlib import import_module\n",
        "m = __import__(name)\n",
    ],
)
def test_dynamic_import_is_caught(tmp_path, rules, code):
    res = run_guard(_pkg(tmp_path, {"predict/dyn.py": code}), rules)
    assert any("動的な import" in v for v in res.violations), res.violations


@pytest.mark.parametrize("rel", ["util.py", "run/__init__.py", "run/jobs.py"])
def test_new_modules_are_scanned_by_default(tmp_path, rules, rel):
    # 予測側のパッケージ以外に足したモジュールも検査の対象（eval/ だけが対象外）
    src = _pkg(tmp_path, {})
    (src / rel).parent.mkdir(parents=True, exist_ok=True)
    (src / rel).write_text("from jpcalc.eval import gold\nP = 'policy.json'\n", encoding="utf-8")
    res = run_guard(src, rules)
    assert len(res.violations) == 2, res.violations


def test_docstrings_are_exempt(tmp_path, rules):
    code = '"""policy.json は予測側で開かない。"""\n\ndef f():\n    """answers/ は評価側だけ。"""\n'
    assert run_guard(_pkg(tmp_path, {"predict/doc.py": code}), rules).ok


def test_eval_package_is_not_scanned(tmp_path, rules):
    src = _pkg(tmp_path, {"eval/gold.py": "P = 'calc/spec.json'\n"})
    assert run_guard(src, rules).ok


def test_syntax_error_is_reported(tmp_path, rules):
    res = run_guard(_pkg(tmp_path, {"pdfread/x.py": "def (:\n"}), rules)
    assert any("構文エラー" in v for v in res.violations)


def test_rules_cover_both_corpora():
    g = load_guard_config()
    for name in (
        "policy.json",
        "contract.json",
        "calendar.json",
        "tasks.jsonl",
        "layout.json",
        "index.json",
        "documents.jsonl",
    ):
        assert name in g.forbidden_names
    assert set(g.strict_dir_names) >= {"calc", "answers", "views"}
    assert set(g.boundary_dir_parts) >= {"tests/", "programs/", "pages/"}


def test_find_forbidden_reports_each_hit(rules):
    assert set(find_forbidden("answers/x/spec.json", rules)) == {"spec.json", "answers"}


def test_make_shots_is_eval_launcher_but_predict_is_not(tmp_path, rules):
    # 手本作りは正解を読む評価側の入口なので許す。予測の入口から評価側を import したら止める
    ok = "def _cmd_make_shots(a):\n    from .eval.shots import make_shots\n"
    assert run_guard(_pkg(tmp_path, {"cli.py": ok}), rules).ok
    bad = "def _cmd_predict(a):\n    from .eval.shots import make_shots\n"
    res = run_guard(_pkg(tmp_path / "b", {"cli.py": bad}), rules)
    assert not res.ok and any("_cmd_predict" in v for v in res.violations)

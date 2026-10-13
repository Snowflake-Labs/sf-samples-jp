"""正解漏れガードが違反を**実際に検出できる**ことの実証（逆対照）。

常に通るガードは無価値なので、違反を仕込んだ一時ディレクトリを検査させる。
"""

from __future__ import annotations

import json

from jpdocread.common.guard import (
    GuardResult,
    check_donors_excluded,
    check_entry_modules,
    check_no_eval_import,
    check_no_gold_filenames,
    run_guard,
)
from jpdocread.common.paths import FORBIDDEN_DOC_PATHS, FORBIDDEN_GOLD_FILES


def _check(fn, tmp_path, body: str) -> GuardResult:
    (tmp_path / "bad.py").write_text(body, encoding="utf-8")
    res = GuardResult()
    fn(res, tmp_path)
    return res


class TestDetectsViolations:
    def test_absolute_eval_import(self, tmp_path):
        res = _check(check_no_eval_import, tmp_path, "from jpdocread.eval.gold import load\n")
        assert not res.ok and "imports eval module" in res.violations[0]

    def test_plain_eval_import(self, tmp_path):
        assert not _check(check_no_eval_import, tmp_path, "import jpdocread.eval.gold\n").ok

    def test_relative_eval_import(self, tmp_path):
        assert not _check(check_no_eval_import, tmp_path, "from ..eval import gold\n").ok

    def test_from_dot_import_eval(self, tmp_path):
        assert not _check(check_no_eval_import, tmp_path, "from . import eval\n").ok

    def test_each_forbidden_name(self, tmp_path):
        for i, bad in enumerate(FORBIDDEN_GOLD_FILES + FORBIDDEN_DOC_PATHS):
            d = tmp_path / f"c{i}"
            d.mkdir()
            assert not _check(check_no_gold_filenames, d, f'X = "x/{bad}"\n').ok, bad

    def test_syntax_error_is_a_violation(self, tmp_path):
        assert not _check(check_no_eval_import, tmp_path, "def (:\n").ok

    def test_shot_from_non_donor(self, tmp_path):
        (tmp_path / "contract").mkdir()
        shot = {"doc_id": "not-0001--ct-a4-1col-mincho", "figure_id": "fig_x"}
        (tmp_path / "contract" / "figure__not-0001--ct-a4-1col-mincho__fig_x.json").write_text(
            json.dumps(shot), encoding="utf-8"
        )
        res = GuardResult()
        check_donors_excluded(res, shots_dir=tmp_path)
        assert not res.ok and "not-0001--ct-a4-1col-mincho" in res.violations[0]

    def test_donor_shot_with_double_dash_doc_id_passes(self, tmp_path):
        """doc_id 自体が `--` を含むので、ファイル名の分割ではなく JSON の doc_id で判定する（回帰テスト）。"""
        from jpdocread.config import load_corpus_config

        for corpus in ("yakkan", "contract"):
            (tmp_path / corpus).mkdir()
            for d in load_corpus_config(corpus).figure_shots:
                (tmp_path / corpus / f"figure__{d}__fig_a.json").write_text(
                    json.dumps({"doc_id": d, "figure_id": "fig_a"}), encoding="utf-8"
                )
        res = GuardResult()
        check_donors_excluded(res, shots_dir=tmp_path)
        assert res.ok, res.violations


class TestAllowsCleanCode:
    def test_builtin_eval_call_is_not_an_import(self, tmp_path):
        assert _check(check_no_eval_import, tmp_path, "x = eval('1')\n").ok

    def test_docstring_may_mention_gold_files(self, tmp_path):
        body = '"""answer.json は読まない。"""\n\ndef f():\n    """pages/ も読まない。"""\n'
        assert _check(check_no_gold_filenames, tmp_path, body).ok

    def test_repository_passes(self):
        res = run_guard()
        assert res.ok, res.violations
        assert res.checks_run == [
            "no_eval_import",
            "no_gold_filenames",
            "entry_modules",
            "donors_excluded",
        ]


class TestEntryModules:
    """read/ の外にある予測経路の入口（jobs.py・worker.py）で、eval の import を採点側の関数に限る。"""

    def _run(self, tmp_path, body: str) -> GuardResult:
        p = tmp_path / "entry.py"
        p.write_text(body, encoding="utf-8")
        res = GuardResult()
        check_entry_modules(res, {p: frozenset({"cmd_s60"})})
        return res

    def test_import_inside_allowed_function_passes(self, tmp_path):
        assert self._run(tmp_path, "def cmd_s60():\n    from .eval.evaluate import evaluate\n").ok

    def test_module_level_import_is_a_violation(self, tmp_path):
        res = self._run(tmp_path, "from .eval.evaluate import evaluate\n")
        assert not res.ok and "モジュールの先頭" in res.violations[0]

    def test_import_in_predict_function_is_a_violation(self, tmp_path):
        res = self._run(tmp_path, "def cmd_s50():\n    from .eval import evaluate\n")
        assert not res.ok and "cmd_s50" in res.violations[0]

    def test_missing_module_is_a_violation(self, tmp_path):
        res = GuardResult()
        check_entry_modules(res, {tmp_path / "none.py": frozenset()})
        assert not res.ok

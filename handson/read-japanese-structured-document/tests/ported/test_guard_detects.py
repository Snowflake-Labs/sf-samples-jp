"""ガードが**違反を実際に検出できる**ことの実証。

常に通るガードは無価値である。ここでは違反を仕込んだ一時ディレクトリを検査させ、
検出されることを確認する（逆対照）。
"""

from __future__ import annotations

from jpdocread.common.guard import GuardResult, check_no_eval_import, check_no_gold_filenames


def _write(tmp_path, name: str, body: str):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


class TestGuardDetectsViolations:
    def test_detects_absolute_eval_import(self, tmp_path):
        _write(tmp_path, "bad.py", "from jpdocread.eval.gold import load_gold\n")
        res = GuardResult()
        check_no_eval_import(res, tmp_path)
        assert not res.ok
        assert "imports eval module" in res.violations[0]

    def test_detects_plain_eval_import(self, tmp_path):
        _write(tmp_path, "bad.py", "import jpdocread.eval.gold\n")
        res = GuardResult()
        check_no_eval_import(res, tmp_path)
        assert not res.ok

    def test_detects_relative_eval_import(self, tmp_path):
        _write(tmp_path, "bad.py", "from ..eval import gold\n")
        res = GuardResult()
        check_no_eval_import(res, tmp_path)
        assert not res.ok

    def test_detects_from_dot_import_eval(self, tmp_path):
        _write(tmp_path, "bad.py", "from . import eval\n")
        res = GuardResult()
        check_no_eval_import(res, tmp_path)
        assert not res.ok

    def test_detects_gold_filename_literal(self, tmp_path):
        _write(tmp_path, "bad.py", 'P = "docs/x/answer.json"\n')
        res = GuardResult()
        check_no_gold_filenames(res, tmp_path)
        assert not res.ok
        assert "answer.json" in res.violations[0]

    def test_detects_each_forbidden_gold_file(self, tmp_path):
        from jpdocread.common.paths import FORBIDDEN_GOLD_FILES

        for i, bad in enumerate(FORBIDDEN_GOLD_FILES):
            d = tmp_path / f"c{i}"
            d.mkdir()
            _write(d, "bad.py", f'X = "{bad}"\n')
            res = GuardResult()
            check_no_gold_filenames(res, d)
            assert not res.ok, f"{bad} を検出できていない"

    def test_clean_module_passes(self, tmp_path):
        """逆対照：問題のないモジュールは通ること（感度があるだけでなく特異性もある）。"""
        _write(
            tmp_path,
            "ok.py",
            "from ..common.paths import doc_pdf\n\n\ndef f():\n    return doc_pdf('x')\n",
        )
        res = GuardResult()
        check_no_eval_import(res, tmp_path)
        check_no_gold_filenames(res, tmp_path)
        assert res.ok, res.violations

    def test_doc_pdf_is_allowed_but_pages_is_not(self, tmp_path):
        """予測側が開いてよいのは `doc.pdf` だけ（R6）。親が許していた `pages/` は D-019 で禁止にした。"""
        _write(tmp_path, "ok.py", 'A = "doc.pdf"\n')
        res = GuardResult()
        check_no_gold_filenames(res, tmp_path)
        assert res.ok, res.violations
        _write(tmp_path, "bad.py", 'B = "pages/page-001.png"\n')
        res = GuardResult()
        check_no_gold_filenames(res, tmp_path)
        assert not res.ok and "pages/" in res.violations[0]


def test_docstring_mentioning_gold_is_allowed(tmp_path):
    """docstring での言及は違反にしない（コメントと同じ扱い）。"""
    d = tmp_path / "src" / "jpdocread" / "read"
    d.mkdir(parents=True)
    (d / "m.py").write_text(
        '"""説明。layout.json は見ない。"""\n\n\ndef f():\n    """answer.json も使わない。"""\n    return 1\n',
        encoding="utf-8",
    )
    res = GuardResult()
    check_no_gold_filenames(res, root=tmp_path)
    assert res.violations == [], res.violations


def test_nondocstring_string_still_detected(tmp_path):
    """docstring 以外の文字列は従来どおり検出する（免除の範囲が広すぎないこと）。"""
    d = tmp_path / "src" / "jpdocread" / "read"
    d.mkdir(parents=True)
    (d / "m.py").write_text(
        '"""ok."""\n\nX = "layout.json"\n\n\ndef f():\n    """ok."""\n    y = "answer.json"\n    return y\n',
        encoding="utf-8",
    )
    res = GuardResult()
    check_no_gold_filenames(res, root=tmp_path)
    assert len(res.violations) == 2, res.violations

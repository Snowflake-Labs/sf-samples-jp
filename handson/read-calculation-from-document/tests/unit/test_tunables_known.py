"""読み出し口の許可表（KNOWN）と本体の `tun` の呼び出しの一致、validate の検査。"""

import ast
from pathlib import Path

from jpcalc.common.tunables import KNOWN, validate
from jpcalc.pdfread.geometry import TABLE_SETTING_KEYS

SRC = Path(__file__).resolve().parents[2] / "src" / "jpcalc"


def _called_names() -> tuple[set[str], list[str]]:
    lit, other = set(), []
    for p in SRC.rglob("*.py"):
        if p.name == "tunables.py":
            continue
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "tun":
                a = n.args[0]
                if isinstance(a, ast.Constant):
                    lit.add(a.value)
                else:
                    other.append(f"{p.name}:{ast.unparse(a)}")
    return lit, other


def test_known_matches_core_calls():
    lit, other = _called_names()
    built = {f"table.{k}" for k in TABLE_SETTING_KEYS}
    # 名前を組み立てて読む口は geometry の table.* だけ（増えたら表と、この検査を直す）
    assert other == ["geometry.py:f'table.{k}'"]
    assert set(KNOWN) == lit | built


def test_validate():
    assert validate({}) == []
    assert (
        validate(
            {"j1.title_cues": ["期限", "喪失"], "geom.gutter_thr": 0.9, "pdoc.frame_min_h": 30}
        )
        == []
    )
    assert validate({"geom.gutter_thr": 1}) == []  # int は float の位置に可
    probs = validate(
        {"j1.nope": ["a"], "pdoc.frame_min_h": 3.5, "geom.y_tol": True, "j1.cues_extra": [1]}
    )
    assert len(probs) == 4


def test_corpus_tuning_rejects_coercible_values(tmp_path):
    import shutil

    import pytest
    import yaml

    from jpcalc.common.paths import CORPORA
    from jpcalc.config import ConfigError, load_corpus_config

    shutil.copy(CORPORA / "yakkan.yaml", tmp_path / "yakkan.yaml")
    y = yaml.safe_load((tmp_path / "yakkan.yaml").read_text(encoding="utf-8"))
    for bad in ({"geom.y_tol": True}, {"geom.y_tol": "1.5"}, {"j1.title_cues": "期限"}):
        y["tuning"] = bad
        (tmp_path / "yakkan.yaml").write_text(
            yaml.safe_dump(y, allow_unicode=True), encoding="utf-8"
        )
        with pytest.raises(ConfigError):
            load_corpus_config("yakkan", tmp_path)

"""生成コードへの埋め込みと静的検査の逆対照。

計算仕様の文字列（AI の出力・PDF の表記）は、生成コードのコメントと docstring にしか入らず、文にならないこと。
静的検査は、許可した import・属性・構文の外を落とすこと。識別子は、予約語・補助関数・ほかの関数と衝突しないこと。
評価は、予測側の書いたモジュールではなく、仕様から作り直したモジュールを採点すること。
"""

import ast
import copy
import os

import pytest
from fixtures.spec_fixtures import C1, C3, GOOD, S1, S2, S3

from jpcalc.eval import evaluate
from jpcalc.predict import codegen, codegen_check, spec

INJECT = "x\r    import calendar as _k; _k.sys.modules['os'].environ['JPCALC_INJECTED'] = '1' #"


def _body_sizes(src: str) -> dict[str, int]:
    tree = ast.parse(src)
    return {n.name: len(n.body) for n in tree.body if isinstance(n, ast.FunctionDef)}


def _strip_docstrings(src: str) -> str:
    return ast.dump(evaluate.strip_docstrings(ast.parse(src)))


def _run(src: str) -> dict:
    ns: dict = {}
    exec(compile(src, "<gen>", "exec"), ns)  # noqa: S102  テストの中で生成コードを動かす
    return ns


@pytest.fixture(autouse=True)
def _no_injected_env(monkeypatch):
    monkeypatch.delenv("JPCALC_INJECTED", raising=False)
    yield
    assert "JPCALC_INJECTED" not in os.environ


@pytest.mark.parametrize(
    "text",
    [
        INJECT,
        "a\u2028    _k = 1",
        "a\x0b    _k = 1",
        'a"""\n    _k = 1\n    """',
        "a\\N{x}",
        "a\x00b",
    ],
)
def test_free_text_never_becomes_code(text):
    s = copy.deepcopy(S2)
    s["doc_id"] = text
    s["rules"][0]["title"] = text
    s["rules"][0]["evidence_units"] = [text, "p1"]
    s["rules"][0]["steps"][0]["label"] = text
    s["params"]["unit"]["text"] = text
    s["params"]["unit"]["source"] = {"unit": text}
    for t in s["tables"].values():
        t["block_id"] = text
    clean = codegen.generate(S2)
    src = codegen.generate(s)
    assert codegen_check.check_module(src) == []
    assert _body_sizes(src) == _body_sizes(clean)
    assert _strip_docstrings(src) == _strip_docstrings(clean)
    ns = _run(src)
    assert ns["grade_pay"](amt=15000000, grade=3) == 12000000


def test_review_reproduction_cases_are_inert():
    """公開前レビュー（2 回目）の再現の 2 例：ステップの題名と定数の表記の \\r。"""
    s = copy.deepcopy(S1)
    s["rules"][0]["steps"][0]["label"] = INJECT
    s["params"]["ded"]["text"] = (
        "免責\r_calendar.sys.modules['os'].environ['JPCALC_INJECTED']='p' #"
    )
    assert spec.check(s, C1) == []
    src = codegen.generate(s)
    assert codegen_check.check_module(src) == []
    assert _run(src)["pay"](a=20000, b=0) == 10000


@pytest.mark.parametrize(
    "src",
    [
        "import calendar as _c\n_c.sys.modules['os'].system('true')\n",
        "import fractions\nfractions.sys.modules['builtins'].open('x')\n",
        "import datetime as _dt\nx = _dt.sys\n",
        "from fractions import sys as s\n",
        "from calendar import monthrange as m, sys\n",
        "import calendar as c\nx = c.TextCalendar\n",
        "class A:\n    pass\n",
        "def __eq__(a, b):\n    return True\n",
        "def f():\n    global g\n    g = 1\n",
        "def f():\n    x = 1\n    def g():\n        nonlocal x\n        x = 2\n",
        "x = 1\nwhile True:\n    pass\n",
        "try:\n    pass\nexcept Exception:\n    pass\n",
        "with x:\n    pass\n",
        "x = (yield 1)\n",
        "x = [1][0].__class__\n",
        "import calendar as _calendar\nx = _calendar.monthrange.__globals__\n",
    ],
)
def test_static_check_rejects_outside_the_allowlist(src):
    assert codegen_check.check_module(src) != [], src


@pytest.mark.parametrize("s,c", GOOD)
def test_static_check_accepts_generated_modules(s, c):
    assert codegen_check.check_module(codegen.generate(s)) == []


def _rename_input(s, old, new):
    r = s["rules"][0]
    for i in r["inputs"]:
        if i["name"] == old:
            i["name"] = new

    def walk(e):
        if isinstance(e, dict):
            if e.get("var") == old:
                e["var"] = new
            for v in e.values():
                walk(v)
        elif isinstance(e, list):
            for v in e:
                walk(v)

    walk(r["steps"])
    return s


@pytest.mark.parametrize("bad", ["from", "in", "t_add", "_norm", "A", "a-b", "1a", ""])
def test_spec_check_rejects_unsafe_input_names(bad):
    s = _rename_input(copy.deepcopy(S1), "a", bad)
    assert any("identifier" in p for p in spec.check(s)), bad


@pytest.mark.parametrize("bad", ["t_add", "int", "len", "class", "_norm", "Pay"])
def test_spec_check_rejects_unsafe_function_names(bad):
    s = copy.deepcopy(S1)
    s["rules"][0]["function"] = bad
    # 大文字などはスキーマの pattern が先に落とす。どちらで落ちても、その関数の問題になる
    assert any(("identifier" in p or "schema" in p) for p in spec.check(s)), bad


def test_spec_check_rejects_colliding_constant_names():
    s = copy.deepcopy(S1)
    s["params"]["d-x"] = dict(s["params"]["ded"])
    s["params"]["d_x"] = dict(s["params"]["ded"])
    assert any("identifier" in p for p in spec.check(s))


def test_spec_check_rejects_input_shadowing_a_called_rule():
    """呼ぶ規則と同じ名前の入力は、生成コードでは関数を隠して呼び出しが失敗する（インタプリタと結果が食い違う）。"""
    s = copy.deepcopy(S3)
    pay = next(r for r in s["rules"] if r["function"] == "elig_pay")
    s["rules"] = [pay, *[r for r in s["rules"] if r is not pay]]
    _rename_input(s, pay["inputs"][0]["name"], "elig")
    assert any("rule this function calls" in p for p in spec.check(s))
    # 呼ばない規則と同じ名前なら、生成コードは正しく動くので落とさない
    s2 = copy.deepcopy(S2)
    _rename_input(s2, s2["rules"][0]["inputs"][0]["name"], s2["rules"][1]["function"])
    assert not any("identifier" in p for p in spec.check(s2))


def test_good_specs_still_pass_identifier_checks():
    for s, c in GOOD:
        assert spec.check(s, c) == []


def test_evaluation_regenerates_from_the_spec():
    src = codegen.generate(S1)
    out, prob = evaluate.regenerate(S1, src)
    assert prob is None and out == src
    tampered = src + "\nimport calendar as _c\n_X = _c.monthrange(2024, 1)\n"
    out, prob = evaluate.regenerate(S1, tampered)
    assert out is None and "regenerated_mismatch" in prob
    # docstring・コメントだけの違いは同じとみなす（作り直したものを採点に使う）
    relabeled = copy.deepcopy(S1)
    relabeled["rules"][0]["title"] = "別の題名"
    out, prob = evaluate.regenerate(relabeled, src)
    assert prob is None and out == codegen.generate(relabeled)


def test_evaluation_regenerates_only_the_functions_in_the_module():
    """予測側は使えない関数を外して生成する（usable_subset）。評価はモジュールにある関数だけで作り直す。"""
    sub = dict(S2, rules=[S2["rules"][0]])
    src = codegen.generate(sub)
    out, prob = evaluate.regenerate(S2, src)
    assert prob is None and out == src


def test_structural_literals_have_no_warning():
    for s, _ in GOOD:
        assert spec.warnings(s) == []


def test_non_structural_literal_is_a_warning_not_a_problem():
    """構造上の数（0・1・100）でない整数は警告として記録し、仕様の検査では落とさない。"""
    s = copy.deepcopy(S1)
    s["rules"][0]["steps"][-1]["expr"]["args"][0] = {"lit": 12}
    assert spec.check(s, C1) == []
    assert spec.warnings(s) == ["pay: lit outside [0, 1, 100] (use a value span): [12]"]


def test_runtime_error_in_the_spec_goes_to_d_repair():
    """仕様から作ったケースで、生成コードもインタプリタも例外（日付と整数の足し算）なら spec_error として D に戻す。"""
    from fixtures.spec_fixtures import I, card

    from jpcalc.predict import r_repair, t_selftest

    s = {
        "spec_version": "jpcalc-1",
        "doc_id": "fx",
        "params": {},
        "tables": {},
        "rules": [
            {
                "function": "due",
                "kind": "calculation",
                "output_type": "int",
                "inputs": [I("d", "date")],
                "steps": [{"name": "x", "expr": {"op": "add", "args": [{"var": "d"}, {"lit": 1}]}}],
                "output": "x",
            }
        ],
    }
    cards = [card("due", [I("d", "date")])]
    tr = t_selftest.run(s, codegen.generate(s), cards, [], n_random=5)
    layers = {f["layer"] for f in tr["fails"]}
    assert layers == {"spec_error"} and tr["by_function"] == {"due": False}
    assert r_repair.needs_d_repair(tr["fails"])
    assert all("interp_msg" in f for f in tr["fails"])


def _two_rules():
    """入力 a を使う健全な規則 good と、問題のある規則 bad。"""
    s = copy.deepcopy(S1)
    good = copy.deepcopy(s["rules"][0])
    good["function"] = "good"
    bad = copy.deepcopy(s["rules"][0])
    bad["function"] = "bad"
    s["rules"] = [good, bad]
    cards = [card_of(r) for r in s["rules"]]
    return s, cards


def card_of(r):
    return {"function": r["function"], "inputs": r["inputs"], "output": {"type": "int"}}


def test_usable_subset_keeps_healthy_rules_when_another_has_a_problem():
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    sub, dropped = d_spec.usable_subset(s, cards, ["bad: unused inputs ['a']"])
    assert dropped == ["bad"] and [r["function"] for r in sub["rules"]] == ["good"]


def test_usable_subset_ignores_words_of_unattributed_schema_messages():
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    sub, dropped = d_spec.usable_subset(
        s, cards, ["schema: 'name' is a required property at ['x']"]
    )
    assert dropped == [] and len(sub["rules"]) == 2


def test_usable_subset_drops_only_rules_using_a_broken_constant():
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    s["params"]["v099"] = {"value": 5, "unit": "JPY"}
    s["rules"][1]["steps"][1]["expr"]["args"][1] = {"param": "v099"}
    sub, dropped = d_spec.usable_subset(
        s, cards, ["params key identifier 'v099' collides with 'V099'"]
    )
    assert dropped == ["bad"] and [r["function"] for r in sub["rules"]] == ["good"]


def test_spec_check_requires_the_output_type():
    s = copy.deepcopy(S3)
    del s["rules"][0]["output_type"]
    assert any("output_type None" in p for p in spec.check(s, C3))


def test_usable_subset_drops_the_rule_using_an_unresolved_constant():
    """`param v002: …` の形（引用符が無い）でも、その定数を使う関数だけを外す（文書ごと落とさない）。"""
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    s["params"]["v099"] = {"value": "二十日", "unit": "DAY"}
    s["rules"][1]["steps"][1]["expr"]["args"][1] = {"param": "v099"}
    probs = spec.check(s, cards)
    assert probs and probs[0].startswith("param v099:")
    sub, dropped = d_spec.usable_subset(s, cards, probs)
    assert dropped == ["bad"] and [r["function"] for r in sub["rules"]] == ["good"]


def test_usable_subset_matches_table_names_exactly():
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    s["rules"][0]["steps"][0]["expr"] = {
        "op": "lookup",
        "table": "t10__exact",
        "args": [{"var": "a"}],
    }
    s["rules"][1]["steps"][0]["expr"] = {
        "op": "lookup",
        "table": "t1__exact",
        "args": [{"var": "a"}],
    }
    s["tables"] = {"t1__exact": {}, "t10__exact": {}}
    _, dropped = d_spec.usable_subset(s, cards, ["tables key identifier 't1__exact' collides"])
    assert dropped == ["bad"]


def test_usable_subset_attributes_a_problem_to_every_function_it_names():
    from jpcalc.predict import d_spec

    s, cards = _two_rules()
    _, dropped = d_spec.usable_subset(s, cards, ["bad.steps[0]: calls good: wrong arity"])
    assert dropped == ["bad", "good"]

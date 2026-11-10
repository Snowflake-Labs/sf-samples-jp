"""仕様の検証（正しいもの 5・壊したもの 10）と、インタプリタ ↔ 生成コードの一致。"""

import datetime as dt

import pytest
from fixtures.spec_fixtures import GOOD, S1, S2, S3, S4, S5, broken

from jpcalc.predict import casegen, codegen, runner, spec
from jpcalc.predict.interp import Interp


@pytest.mark.parametrize("s,c", GOOD)
def test_good_specs_pass(s, c):
    assert spec.check(s, c) == []


@pytest.mark.parametrize("i,s", list(enumerate(broken())))
def test_broken_specs_detected(i, s):
    assert spec.check(s) != [], f"broken spec {i} not detected"


def test_card_mismatch_detected():
    c = [{"function": "pay", "inputs": [{"name": "a", "type": "int"}], "output": {"type": "int"}}]
    assert any("inputs" in p for p in spec.check(S1, c))


def test_interp_hand_values():
    assert Interp(S1).call("pay", a=200000, b=150000) == 300000
    assert Interp(S1).call("pay", a=3000, b=2000) == 0
    assert Interp(S2).call("grade_pay", amt=15000000, grade=3) == 12000000
    assert Interp(S2).call("grade_pay", amt=15000000, grade=9) is None
    assert Interp(S2).call("dec_pay", amt=1000000, years=3) == 800000
    assert Interp(S3).call("elig_pay", damaged=True, days=27, paid_elsewhere=False) == 50000
    assert Interp(S3).call("elig", damaged=False, days=None, paid_elsewhere=None) is False
    assert Interp(S3).call("elig", damaged=True, days=None, paid_elsewhere=False) is None
    assert Interp(S4).call("deadline", doc_date=dt.date(2024, 1, 1)) == dt.date(2024, 1, 30)
    assert Interp(S4).call("lim_pay", cost=900000, policy_limit=None) == 500000
    assert (
        Interp(S5).call("items_pay", items=[{"x": 80000}, {"x": 80000}, {"x": 80000}, {"x": 10}])
        == 150000
    )


@pytest.mark.parametrize("s,c", GOOD)
def test_codegen_matches_interp(s, c):
    src = codegen.generate(s)
    compile(src, "gen.py", "exec")
    it = Interp(s)
    cards = {x["function"]: x for x in c}
    batch, expect = [], []
    for r in s["rules"]:
        cd = cards[r["function"]]
        dates = [i["name"] for i in cd["inputs"] if i["type"] == "date"]
        for case in casegen.generate(s, r, cd, n_random=1000, seed=1):
            batch.append(
                {
                    "function": r["function"],
                    "inputs": casegen.to_json_inputs(case["inputs"]),
                    "date_args": dates,
                }
            )
            expect.append(it.call(r["function"], **case["inputs"]))
    got = runner.run_cases(src, batch)
    errs = [g for g in got if "error" in g]
    assert not errs, errs[:3]
    mism = [
        (b, e, g["value"]) for b, e, g in zip(batch, expect, got, strict=True) if g["value"] != e
    ]
    assert not mism, mism[:3]
    assert len(batch) > 1000


def test_schema_error_in_one_rule_keeps_the_others():
    """1 つの関数の explicit の型の誤りで、文書全体のモジュールを失わない。"""
    import copy

    from jpcalc.predict import d_spec

    s, c = copy.deepcopy(GOOD[1])
    s["rules"][1]["explicit"] = ["文字列の列になった"]
    probs = spec.check(s, c)
    assert probs and all(p.startswith(f"{s['rules'][1]['function']}: schema:") for p in probs)
    sub, bad = d_spec.usable_subset(s, c, probs)
    assert bad == [s["rules"][1]["function"]]
    assert sub is not None and [r["function"] for r in sub["rules"]] == [s["rules"][0]["function"]]
    # 規則の外の誤り（関数に帰属しない）には関数名を付けない
    s2 = copy.deepcopy(GOOD[0][0])
    s2["params"] = []
    assert all(p.startswith("schema:") for p in spec.check(s2))


def test_explicit_notes_list_is_kept_as_record():
    from jpcalc.predict import d_spec

    assert d_spec._explicit(["「90日を超えて」はgt"]) == {"notes": ["「90日を超えて」はgt"]}
    assert d_spec._explicit("切り捨て") == {"notes": ["切り捨て"]}
    assert d_spec._explicit(None) == {} and d_spec._explicit({"rounding": "floor"}) == {
        "rounding": "floor"
    }
    assert d_spec._explicit([1, 2]) == [1, 2]  # 想定外の形は直さずに検査に回す

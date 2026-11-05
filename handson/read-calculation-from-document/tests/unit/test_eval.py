"""評価側（正解の照合・対応付け M・採点・逆対照・台帳）の試験。正解は合成の最小のものをテスト中に作る。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from jpcalc.common.paths import HOME
from jpcalc.eval import controls, evaluate, match, score, store
from jpcalc.eval.gold import Gold, GoldMismatch, file_matches, git_blob_sha1, write_ids
from jpcalc.predict import codegen

CONFTEST = """
import importlib.util
from pathlib import Path
import pytest

def pytest_addoption(parser):
    parser.addoption("--impl", default=None)

@pytest.fixture(scope="session")
def impl(request):
    p = Path(request.config.getoption("--impl") or sorted((Path(__file__).parent.parent / "programs").glob("calc_*.py"))[0])
    spec = importlib.util.spec_from_file_location("impl_under_test", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
"""
TEST = """
import json
from datetime import date
from pathlib import Path
import pytest

CASES = [json.loads(x) for x in (Path(__file__).parent.parent / "cases.jsonl").read_text().splitlines() if x]
CAL = {"due_date": True}

@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_case(impl, case):
    kw = {k: (date.fromisoformat(v) if k == "start" else v) for k, v in case["inputs"].items()}
    if CAL.get(case["function"]):
        kw["holidays"] = frozenset(date.fromisoformat(h) for h in case.get("holidays", []))
    got = getattr(impl, case["function"])(**kw)
    want = case["expected"]
    if case["function"] == "due_date":
        want = date.fromisoformat(want)
    assert got == want
"""
PROGRAM = """
import datetime

def fee_amount(*, qty=None):
    return None if qty is None else 1000 + 200 * qty

def due_date(*, start=None, holidays=frozenset()):
    if start is None:
        return None
    d = start + datetime.timedelta(days=1)
    while d in holidays or d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d
"""
TEXT = {
    "meta": {"constants": {}},
    "body": [
        {"id": "a1", "kind": "article", "title": "手数料", "children": [
            {"id": "a1_p1", "kind": "paragraph", "text": "乙は、利用量1単位につき200円に基本料1000円を加えた額の手数料を受け取る。"},
        ]},
        {"id": "a2", "kind": "article", "title": "期日", "children": [
            {"id": "a2_p1", "kind": "paragraph", "text": "納品の日の翌営業日を検収の期日とする。休業日は期日に数えない。"},
        ]},
    ],
}  # fmt: skip
CARDS = [
    {"function": "fee_amount", "title": "データ利用の手数料", "kind": "calculation",
     "inputs": [{"name": "qty", "type": "int", "unit": "COUNT", "desc": "当月の利用量"}],
     "output": {"type": "int", "unit": "JPY"}},
    {"function": "due_date", "title": "検収の期日", "kind": "calculation",
     "inputs": [{"name": "start", "type": "date", "desc": "納品の日"}],
     "output": {"type": "date"}},
]  # fmt: skip
AK = [
    {"rule": "fee_amount", "function": "fee_amount", "pattern": "K02", "units": ["a1_p1"],
     "modalities": ["prose"], "difficulty": {"depth": 1}},
    {"rule": "due_date", "function": "due_date", "pattern": "K14", "units": ["a2_p1"],
     "modalities": ["prose"], "difficulty": {}},
]  # fmt: skip
CASES = [
    {"case_id": "c1", "function": "fee_amount", "kind": "example", "inputs": {"qty": 3}, "expected": 1600},
    {"case_id": "c2", "function": "fee_amount", "kind": "unknown", "inputs": {"qty": None}, "expected": None},
    {"case_id": "c3", "function": "due_date", "kind": "boundary", "inputs": {"start": "2026-01-09"},
     "holidays": ["2026-01-12"], "expected": "2026-01-13"},
]  # fmt: skip


def make_gold(
    root: Path, corpus: str = "contract", doc: str = "zz-0001", *, ids: bool = True
) -> Gold:
    """合成の正解を、コーパスの配置どおりに書く。"""
    g = Gold(corpus, root, doc)
    calc = g.path("calc")
    (calc / "programs").mkdir(parents=True)
    (calc / "tests").mkdir(parents=True)
    (calc / "programs" / "calc_zz.py").write_text(PROGRAM, encoding="utf-8")
    (calc / "tests" / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (calc / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    (calc / "answer_key.json").write_text(json.dumps(AK), encoding="utf-8")
    (calc / "cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in CASES), encoding="utf-8"
    )
    (calc / "manifest.json").write_text(json.dumps({"profile": "standard"}), encoding="utf-8")
    g.path("tasks").parent.mkdir(parents=True, exist_ok=True)
    g.path("tasks").write_text("".join(json.dumps(c) + "\n" for c in CARDS), encoding="utf-8")
    g.path("text").write_text(json.dumps(TEXT, ensure_ascii=False), encoding="utf-8")
    if ids:
        write_ids(
            root,
            {
                f.relative_to(root).as_posix(): {"git_sha1": git_blob_sha1(f.read_bytes())}
                for f in g.files()
            },
        )
    return g


# ---- 正解の照合


def test_git_blob_sha1_matches_git():
    # git hash-object の既知の値（空のファイル）
    assert git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert file_matches(b"", {"git_sha1": "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"})
    assert not file_matches(b"", {})


@pytest.mark.parametrize("corpus", ["yakkan", "contract"])
def test_verify_ok_and_tamper(tmp_path, corpus):
    g = make_gold(tmp_path, corpus)
    v = g.verify()
    assert v["unverified"] == [] and v["verified"] == len(g.files())
    (g.path("calc") / "cases.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(GoldMismatch, match="一致しない"):
        g.verify()


def test_verify_unverified_without_ids(tmp_path):
    g = make_gold(tmp_path, ids=False)
    assert len(g.verify()["unverified"]) == len(g.files())


def test_verify_missing_program(tmp_path):
    g = make_gold(tmp_path)
    (g.path("calc") / "programs" / "calc_zz.py").unlink()
    with pytest.raises(GoldMismatch):
        g.verify()


def test_write_ids_conflict(tmp_path):
    write_ids(tmp_path, {"a": {"git_sha1": "1"}})
    with pytest.raises(GoldMismatch):
        write_ids(tmp_path, {"a": {"git_sha1": "2"}})


def test_layout_paths_differ_by_corpus(tmp_path):
    assert Gold("yakkan", tmp_path, "x-1--s").rel("tasks") == "documents/x-1/calc/tasks.jsonl"
    assert Gold("contract", tmp_path, "x-1--s").rel("tasks") == "inputs/x-1/tasks.jsonl"
    assert Gold("contract", tmp_path, "x-1").rel("text") == "inputs/x-1/contract.json"


# ---- 対応付け M


def _gen(function, title, text, kind="calculation", out="int", unit="JPY", inputs=None):
    return {
        "function": function, "title": title, "kind": kind, "evidence_text": text,
        "output": {"type": out, "unit": unit},
        "inputs": inputs or [{"name": "units_used", "type": "int", "unit": "COUNT", "desc": "当月の利用量"}],
    }  # fmt: skip


def _gold_text(tmp_path):
    g = make_gold(tmp_path)
    return g, match.gold_evidence(g.task_cards(), g.answer_key(), g.text_json())


def test_match_filters_kind_and_output(tmp_path):
    g, gt = _gold_text(tmp_path)
    text = TEXT["body"][0]["children"][0]["text"]
    wrong_kind = _gen("x", "データ利用の手数料", text, kind="decision", out="int")
    wrong_out = _gen("y", "データ利用の手数料", text, out="bool")
    mp = match.build_map("p", g.task_cards(), gt, [wrong_kind, wrong_out])
    assert mp["functions"] == {} and set(mp["unmatched_gold"]) == {"fee_amount", "due_date"}


def test_match_determination_is_decision():
    g = {
        "function": "g",
        "kind": "determination",
        "title": "支払の可否",
        "output": {"type": "bool"},
        "inputs": [],
    }
    p = {
        "function": "p",
        "kind": "decision",
        "title": "支払の可否",
        "output": {"type": "bool"},
        "inputs": [],
    }
    fmap, _ = match.match_functions([g], {"g": ["支払の要件を満たすときに限り支払う。"]}, [p],
                                    {"p": "支払の要件を満たすときに限り支払う。"})  # fmt: skip
    assert fmap == {"g": "p"}


def test_match_needs_evidence_floor(tmp_path):
    g, gt = _gold_text(tmp_path)
    # 題名は同じでも根拠の本文が別の規定なら対応させない
    p = _gen("fee", "データ利用の手数料", "契約期間は一年とし、更新は書面による。")
    assert match.build_map("p", g.task_cards(), gt, [p])["functions"] == {}


def test_match_one_to_one_and_deterministic(tmp_path):
    g, gt = _gold_text(tmp_path)
    text = TEXT["body"][0]["children"][0]["text"]
    a = _gen("fee_a", "データ利用の手数料", text)
    b = _gen("fee_b", "データ利用の手数料", text)
    m1 = match.build_map("p", g.task_cards(), gt, [a, b])
    m2 = match.build_map("p", g.task_cards(), gt, [b, a])
    assert m1["functions"]["fee_amount"]["gen"] == m2["functions"]["fee_amount"]["gen"] == "fee_a"
    assert m1["extra_gen"] == ["fee_b"]


def test_match_args_by_type_unit_and_desc():
    g = [{"name": "qty", "type": "int", "unit": "COUNT", "desc": "当月の利用量"}]
    p = [
        {"name": "fee", "type": "int", "unit": "JPY", "desc": "当月の利用量"},
        {"name": "units_used", "type": "int", "unit": "COUNT", "desc": "当月の利用量"},
        {"name": "late", "type": "bool", "desc": "遅延があった"},
    ]
    amap, _, amb = match.match_args(g, p)
    assert amap == {"qty": "units_used"} and amb == 0


def test_identity_map_and_adapter_controls_pass(tmp_path):
    g = make_gold(tmp_path)
    c = controls.run_controls(g)
    assert c["ok"], c
    assert c["identity_map"] == "2/2" and c["identity_adapter"] == "3/3"


def test_controls_detect_broken_reference(tmp_path):
    g = make_gold(tmp_path, ids=False)
    p = g.path("calc") / "programs" / "calc_zz.py"
    p.write_text(PROGRAM.replace("200 * qty", "300 * qty"), encoding="utf-8")
    write_ids(
        tmp_path,
        {
            f.relative_to(tmp_path).as_posix(): {"git_sha1": git_blob_sha1(f.read_bytes())}
            for f in g.files()
        },
    )
    assert not controls.run_controls(g)["ok"]


def test_scoring_refuses_unverified_gold(tmp_path):
    g = make_gold(tmp_path, ids=False)
    with pytest.raises(GoldMismatch, match="照合値の無い"):
        score.run_pytest(g, g.reference_program())


def test_duplicate_case_ids_are_anded(tmp_path):
    g = make_gold(tmp_path)
    t = g.tests_dir() / "test_dup.py"
    t.write_text(
        TEST.replace("assert got == want", "assert case['case_id'] != 'c1'"), encoding="utf-8"
    )
    write_ids(
        tmp_path, {t.relative_to(tmp_path).as_posix(): {"git_sha1": git_blob_sha1(t.read_bytes())}}
    )
    r = score.run_pytest(g, g.reference_program())
    assert r["case_pass"] == {"c1": False, "c2": True, "c3": True}


def test_partial_run_is_an_error(tmp_path):
    g = make_gold(tmp_path)
    t = g.tests_dir() / "test_calc.py"
    t.write_text(
        TEST.replace("CASES = [", "CASES = [c for c in [").replace(
            "if x]", "if x] if c['case_id'] != 'c3']"
        ),
        encoding="utf-8",
    )
    (tmp_path / "gold_ids.json").unlink()
    write_ids(
        tmp_path,
        {
            f.relative_to(tmp_path).as_posix(): {"git_sha1": git_blob_sha1(f.read_bytes())}
            for f in g.files()
        },
    )
    r = score.run_pytest(g, g.reference_program())
    assert r["error"].startswith("partial") and r["case_pass"]["c3"] is False


def test_unsafe_module_is_not_run(tmp_path):
    gold_root = tmp_path / "gold"
    make_gold(gold_root)
    text = TEXT["body"][0]["children"][0]["text"]
    leak = "def fee(*, units_used=None):\n    return open('cases.jsonl').read()\n"
    _write_run(tmp_path / "runs" / "zz-0001--a", [_gen("fee", "データ利用の手数料", text)], leak)
    res = evaluate.evaluate_run(
        "contract", gold_root, tmp_path / "runs", ["zz-0001--a"], tmp_path / "w"
    )
    assert res["n_rules_pass"] == 0 and res["docs"][0]["error"].startswith("unsafe_module")


def _eval_one(tmp_path, module_src, spec, summ=None):
    gold_root = tmp_path / "gold"
    make_gold(gold_root)
    text = TEXT["body"][0]["children"][0]["text"]
    _write_run(
        tmp_path / "runs" / "zz-0001--a", [_gen("fee", "データ利用の手数料", text)], module_src,
        {"fee": True}, spec=spec, summ_extra=summ,
    )  # fmt: skip
    return evaluate.evaluate_run(
        "contract", gold_root, tmp_path / "runs", ["zz-0001--a"], tmp_path / "w"
    )


def test_module_generated_from_the_spec_is_scored(tmp_path):
    res = _eval_one(tmp_path, codegen.generate(FEE_SPEC), FEE_SPEC)
    assert res["n_rules_pass"] == 1 and res["docs"][0]["error"] is None


def test_module_that_differs_from_the_spec_is_not_scored(tmp_path):
    """予測側が書いたモジュールに仕様に無い文を足しても、採点しない（静的検査を通る文でも）。"""
    tampered = codegen.generate(FEE_SPEC) + "\n_X = 1\n"
    res = _eval_one(tmp_path, tampered, FEE_SPEC)
    assert res["n_rules_pass"] == 0
    assert "regenerated_mismatch" in res["docs"][0]["error"]


def test_module_without_a_spec_is_not_scored(tmp_path):
    res = _eval_one(tmp_path, codegen.generate(FEE_SPEC), None)
    assert res["n_rules_pass"] == 0 and "no_spec" in res["docs"][0]["error"]


@pytest.mark.parametrize(
    "summ",
    [
        {"module": "/stage/gold/x/programs/calc_x.py"},
        {"module": "../calc_x.py"},
        {"cards": "../../cards.jsonl"},
        {"final_iteration": "0/../../x"},
    ],
)
def test_summary_paths_outside_the_output_are_rejected(tmp_path, summ):
    res = _eval_one(tmp_path, codegen.generate(FEE_SPEC), FEE_SPEC, summ)
    assert res["n_rules_pass"] == 0 and "bad_path" in res["docs"][0]["error"]


def test_primary_adapter_has_no_fill():
    mp = {"functions": {"f": {"gen": "g", "args": {"a": "b"}, "fields": {}}}}
    src = match.adapter_source("def g(*, b=None):\n    return b\n", mp)
    assert "'fill': {}" in src


# ---- アダプタ


def test_adapter_does_not_fill_extra_args_and_passes_calendar(tmp_path):
    gen_src = """
import datetime
def fee(*, units_used=None, waived=None):
    if waived is None or units_used is None:
        return None
    return 0 if waived else 1000 + 200 * units_used
def nextday(*, delivered=None, holidays=frozenset()):
    d = delivered + datetime.timedelta(days=1)
    while d in holidays or d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d
"""
    mp = {"functions": {
        "fee_amount": {"gen": "fee", "args": {"qty": "units_used"}, "fields": {}, "extra_gen_args": ["waived"]},
        "due_date": {"gen": "nextday", "args": {"start": "delivered"}, "fields": {}, "extra_gen_args": []},
    }}  # fmt: skip
    g = make_gold(tmp_path)
    p = tmp_path / "ad.py"
    p.write_text(match.adapter_source(gen_src, mp), encoding="utf-8")
    sm = score.summarize(g, "p", score.run_pytest(g, p))
    by = {r["function"]: r["passed"] for r in sm["rules"]}
    # 生成側にだけある waived を補わない（None のまま → 不合格）。暦は受け取る関数にだけ渡す（合格）
    assert by == {"fee_amount": False, "due_date": True}
    p.write_text(
        match.adapter_source(gen_src, mp, fill_extra={"fee_amount": {"waived": False}}),
        encoding="utf-8",
    )
    by = {
        r["function"]: r["passed"] for r in score.summarize(g, "p", score.run_pytest(g, p))["rules"]
    }
    assert by["fee_amount"] is True  # 診断の補完では合格（主指標には使わない）


# ---- 採点と集計


FEE_SPEC = {  # 手数料 = 1000 + 200 × 利用量（定数は値スパンの形のキー）
    "spec_version": "jpcalc-1",
    "doc_id": "zz-0001--a",
    "params": {"v001": {"value": 1000, "unit": "JPY"}, "v002": {"value": 200, "unit": "JPY"}},
    "tables": {},
    "rules": [
        {
            "function": "fee",
            "kind": "calculation",
            "output_type": "int",
            "inputs": [{"name": "units_used", "type": "int"}],
            "steps": [
                {
                    "name": "amt",
                    "expr": {
                        "op": "add",
                        "args": [
                            {"param": "v001"},
                            {"op": "mul", "args": [{"param": "v002"}, {"var": "units_used"}]},
                        ],
                    },
                }
            ],
            "output": "amt",
        }
    ],
}


def _write_run(d: Path, cards, module_src: str | None, selftest=None, spec=None, summ_extra=None):
    """予測の生成物の置き場所を作る。評価は仕様（spec_iter<N>.json）から作り直したモジュールだけを採点する。"""
    d.mkdir(parents=True)
    (d / "cards.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards))
    summ = {"cards": "cards.jsonl", "selftest_by_function": selftest or {}}
    if module_src is not None:
        (d / "calc_x.py").write_text(module_src, encoding="utf-8")
        summ["module"] = "calc_x.py"
    if spec is not None:
        (d / "spec_iter0.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        summ["final_iteration"] = 0
    summ.update(summ_extra or {})
    (d / "summary.json").write_text(json.dumps(summ), encoding="utf-8")


def test_evaluate_counts_missing_outputs_in_denominator(tmp_path):
    gold_root = tmp_path / "gold"
    make_gold(gold_root)
    runs = tmp_path / "runs"
    text = TEXT["body"][0]["children"][0]["text"]
    gen_src = codegen.generate(FEE_SPEC)
    _write_run(
        runs / "zz-0001--a", [_gen("fee", "データ利用の手数料", text)], gen_src, {"fee": True},
        spec=FEE_SPEC,
    )  # fmt: skip
    res = evaluate.evaluate_run(
        "contract", gold_root, runs, ["zz-0001--a", "zz-0001--b"], tmp_path / "work",
        {"zz-0001--a": {"style": "a"}, "zz-0001--b": {"style": "b"}},
    )  # fmt: skip
    assert res["n_rules"] == 4  # 2 規則 × 2 PDF（生成物の無い PDF も分母に入る）
    assert res["n_rules_pass"] == 1
    assert res["discovery"]["lost_by_stage"] == {"not_found": 3}
    assert res["coverage"] == 0.5
    assert res["breakdown"]["style"]["a"] == {"n": 2, "pass": 1, "rate": 0.5}
    assert {d["error"] for d in res["docs"]} == {None, "no_output"}
    assert res["selftest_missed"] == 0


def test_lost_stage_order():
    base = {"passed": False, "matched_gen": "f", "args_complete": True, "extra_gen_args": 0}
    assert evaluate.lost_stage(base) == "calculation"
    assert evaluate.lost_stage(base | {"extra_gen_args": 1}) == "interface_extra_args"
    assert evaluate.lost_stage(base | {"args_complete": False}) == "interface"
    assert evaluate.lost_stage(base | {"matched_gen": None}) == "not_found"
    assert evaluate.lost_stage(base | {"passed": True}) is None


def test_score_reports_no_results_on_import_error(tmp_path):
    g = make_gold(tmp_path)
    bad = tmp_path / "bad.py"
    bad.write_text("raise SystemExit('boom')\n", encoding="utf-8")
    r = score.run_pytest(g, bad)
    assert not any(r["case_pass"].values())


# ---- 台帳（Snowflake に接続しない）


class FakeConn:
    def __init__(self):
        self.sql: list[tuple[str, object]] = []

    def cursor(self):
        c = self

        class Cur:
            description = None

            def execute(self, sql, params=None):
                c.sql.append((sql, params))

            def fetchall(self):
                return []

            def close(self):
                pass

        return Cur()


def test_write_db_is_one_transaction():
    res = {
        "run_id": "r", "corpus": "contract", "dataset_revision": "x", "n_pdfs": 1, "n_rules": 1,
        "n_rules_pass": 0, "n_cases": 2, "n_cases_pass": 1, "n_errors": 0, "docs": [],
        "rules": [{"pdf_id": "p", "function": "f", "passed": False, "matched_gen": None,
                   "args_complete": False, "extra_gen_args": 0}],
    }  # fmt: skip
    conn = FakeConn()
    assert store.write_db(conn, res, eval_run_id="r-e1", image_tag=None) == 1
    heads = [s.split()[0] for s, _ in conn.sql]
    assert heads[0] == "BEGIN" and heads[-1] == "COMMIT"
    rows = json.loads(conn.sql[-2][1][2])
    assert rows[0]["lost_stage"] == "not_found"


# ---- ジョブ仕様と SQL


def test_evaluate_job_spec_mounts_only_gold_and_results():
    text = (HOME / "container" / "job_specs" / "evaluate.yaml").read_text(encoding="utf-8")
    vols = yaml.safe_load(text.replace("{{", "'{{").replace("}}", "}}'"))["spec"]["volumes"]
    assert sorted(v["stageConfig"]["name"] for v in vols) == [
        "{{ stage_gold }}",
        "{{ stage_results }}",
    ]
    pred = (HOME / "container" / "job_specs" / "predict.yaml").read_text(encoding="utf-8")
    assert "gold" not in pred


def test_s20_procedure_is_owned_by_eval_role_and_returns_no_scores():
    sql = (HOME / "sql" / "procedures" / "evaluate.sql").read_text(encoding="utf-8")
    assert "USE ROLE <% role_eval %>;" in sql
    assert "GRANT USAGE ON PROCEDURE" in sql and "TO ROLE <% role_predict %>" in sql
    ret = sql[sql.index("RETURN OBJECT_CONSTRUCT") :].split(";")[0]
    assert "pass" not in ret.lower() and "n_rules" not in ret


def test_evidence_diagnostics_do_not_change_the_mapping():
    """生成の根拠が長いと、正解から見た包含（対応付けに使う）は高いままで、生成から見た重なりが下がる。"""
    from jpcalc.eval import match

    gold = ["保険金の額は、損害の額から免責金額を差し引いた額とする。"]
    pred = gold[0] + (
        "なお、この約款に定めのない事項については、日本国の法令に準拠する。保険契約者は、"
        "住所を変更したときは遅滞なく書面で通知しなければならない。当会社は、通知を受けた"
        "後に保険料の返還または追加の請求をすることがある。訴訟の提起は、日本国内の裁判所に限る。"
    )
    d = match.evidence_diagnostics(gold, pred)
    assert match.evidence_overlap(gold, pred) == 1.0
    assert d["gen_precision"] < 0.3 and d["length_ratio"] > 3
    same = match.evidence_diagnostics(gold, gold[0])
    assert same == {"gen_precision": 1.0, "length_ratio": 1.0}
    assert match.evidence_diagnostics([], "x")["length_ratio"] is None

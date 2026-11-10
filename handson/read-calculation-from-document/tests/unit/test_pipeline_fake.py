"""予測のパイプラインを偽の LLM で通す（AI を呼ばない）。

確かめること：段の順序と周回（K → D → T → I → T → R）、最終版の選択、生成物の書き出し、接続が無ければ台帳に
書かないこと、予測の実行中に正解のファイルを開かないこと。応答の内容の良し悪しは確かめない（偽の応答なので）。
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from jpcalc.predict import pipeline
from jpcalc.predict.llm import Resp

DOC = {
    "meta": {"constants": {"v001": "1万円", "v002": "30万円", "v003": "5万円", "v004": "4万円"}},
    "body": [
        {
            "id": "a1",
            "kind": "article",
            "label": "第1条",
            "text": "（保険金の支払額）",
            "children": [
                {
                    "id": "p1",
                    "kind": "paragraph",
                    "label": "①",
                    "text": "当会社が支払う保険金の額は、損害の額から免責金額{const:v001}を差し引いた額とします。"
                    "ただし、{const:v002}を限度とします。",
                    "children": [],
                    "blocks": [],
                }
            ],
            "blocks": [
                {
                    "type": "box",
                    "id": "box1_note",
                    "title": "第1条備考",
                    "blocks": [
                        {
                            "type": "paragraph",
                            "id": "box1_note_p1",
                            "text": "損害の額が{const:v003}のとき、保険金は{const:v004}となります。",
                        }
                    ],
                }
            ],
        }
    ],
}

K_ANSWER = {
    "rules": [
        {
            "function": "pay_amount",
            "title": "保険金の額",
            "kind": "calculation",
            "inputs": [{"name": "loss", "type": "int", "unit": "JPY", "desc": "損害の額"}],
            "output": {"type": "int"},
            "units": ["p1"],
        }
    ],
    "skipped": [],
}

GOOD_RULES = {
    "rules": [
        {
            "function": "pay_amount",
            "kind": "calculation",
            "steps": [
                {
                    "name": "net",
                    "expr": {"op": "sub", "args": [{"var": "loss"}, {"param": "v001"}]},
                },
                {
                    "name": "cap",
                    "expr": {"op": "min", "args": [{"step": "net"}, {"param": "v002"}]},
                },
                {"name": "pay", "expr": {"op": "max", "args": [{"step": "cap"}, {"lit": 0}]}},
            ],
            "output": "pay",
            "explicit": {},
            "unresolved": [],
        }
    ]
}

# 未知の定数を参照する（仕様の検査に落ちる）→ R の周回に入る
BAD_RULES = json.loads(json.dumps(GOOD_RULES).replace('"v002"', '"v999"'))

EXAMPLES = {
    "examples": [
        {
            "function": "pay_amount",
            "source": "box1_note_p1",
            "inputs": {"loss": "5万円"},
            "expected": "4万円",
        }
    ]
}


class FakeLLM:
    """段ごとに決まった応答を返す（AI を呼ばない）。呼ばれた段を順に記録する。"""

    def __init__(self, d_answers: list[dict], r_answers: list[dict] | None = None):
        self.d_answers = list(d_answers)
        self.r_answers = list(r_answers or [])
        self.calls: list[str] = []
        self.stats = {"requests": 0}

    def _answer(self, req):
        st = req.stage
        if st == "K":
            # 初回の K だけ規則を返す。再走査・K-R（別の版）は何も足さない応答
            if req.prompt_version == "k_cards_p1":
                return K_ANSWER
            return {"rules": [], "skipped": [], "candidates": [], "flag_answers": []}
        if st == "D":
            return self.d_answers.pop(0)
        if st == "T_examples":
            return EXAMPLES
        if st == "T_cross":
            return {"results": []}
        if st.startswith("R"):
            return self.r_answers.pop(0)
        raise AssertionError(f"想定外の段: {st}")

    def complete(self, reqs):
        out = []
        for r in reqs:
            self.calls.append(r.stage)
            self.stats["requests"] += 1
            a = self._answer(r)
            out.append(Resp(r, json.dumps(a, ensure_ascii=False), None, parsed=a))
        return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    rev, corpus = "r0", "yakkan"
    pd = tmp_path / corpus / rev / "pdoc"
    pd.mkdir(parents=True)
    (pd / "doc-a.json").write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    cfg = pipeline.load_cfg(env={})
    # 試験を速くする（乱数ケースを減らす）。判定のロジックは変えない
    cfg = cfg.model_copy(update={"selftest": cfg.selftest.model_copy(update={"random_cases": 20})})
    return {"tmp": tmp_path, "rev": rev, "corpus": corpus, "cfg": cfg}


@pytest.fixture
def no_gold_open(monkeypatch):
    """予測の実行中に正解のファイルを開こうとしたら失敗させる。"""
    real = builtins.open

    def guarded(file, *a, **k):
        p = str(file)
        for bad in ("/answers/", "/calc/", "layout.json", "eval_data"):
            assert bad not in p, f"予測側が正解を開こうとした: {p}"
        return real(file, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded)
    real_read = Path.read_text

    def guarded_read(self, *a, **k):
        guarded_path = str(self)
        for bad in ("/answers/", "/calc/", "layout.json", "eval_data"):
            assert bad not in guarded_path, f"予測側が正解を開こうとした: {guarded_path}"
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", guarded_read)


def _run(env, llm):
    return pipeline.run_pdfs(
        None,
        "run1",
        env["corpus"],
        env["rev"],
        ["doc-a"],
        k_shots_text="",
        d_shots_text="",
        cfg=env["cfg"],
        llm=llm,
    )


def test_good_spec_passes_in_one_iteration(env, no_gold_open):
    llm = FakeLLM([GOOD_RULES])
    out = _run(env, llm)
    s = out["doc-a"]
    assert s["error"] is None
    assert s["final_iteration"] == 0 and s["iterations"] == 1
    assert s["selftest_by_function"] == {"pay_amount": True}
    assert s["n_examples"] == 1 and not s["example_errors"]
    # 段の順序：K の後に D、設例、検算。R は呼ばない
    first_d = llm.calls.index("D")
    assert all(c == "K" for c in llm.calls[:first_d])
    assert "T_examples" in llm.calls and not any(c.startswith("R") for c in llm.calls)
    d = env["tmp"] / env["corpus"] / env["rev"] / "runs" / "run1" / "doc-a"
    for f in (
        "cards.jsonl",
        "spec_iter0.json",
        "module_iter0.py",
        "selftest_iter0.json",
        "summary.json",
        "k_lint.json",
        "examples.json",
        "calc_doc_a.py",
    ):
        assert (d / f).is_file(), f
    card = json.loads((d / "cards.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert card["function"] == "pay_amount" and card["evidence_units"] == ["p1"]
    assert s["card_schema_errors"] == []


def test_bad_spec_goes_to_repair_and_recovers(env, no_gold_open):
    llm = FakeLLM([BAD_RULES], r_answers=[GOOD_RULES])
    s = _run(env, llm)["doc-a"]
    assert llm.calls.count("R1") == 1
    assert s["iterations"] == 2 and s["final_iteration"] == 1
    assert s["selftest_by_function"] == {"pay_amount": True}
    assert s["history"][0]["n_spec_probs"] > 0 and s["history"][1]["n_spec_probs"] == 0


def test_repair_stops_at_max_iter(env):
    llm = FakeLLM([BAD_RULES], r_answers=[BAD_RULES] * 5)
    s = pipeline.run_pdfs(
        None,
        "run2",
        env["corpus"],
        env["rev"],
        ["doc-a"],
        k_shots_text="",
        d_shots_text="",
        cfg=env["cfg"],
        llm=llm,
        max_iter=2,
    )["doc-a"]
    assert s["iterations"] == 3 and llm.calls.count("R1") == 1 and llm.calls.count("R2") == 1
    assert s["module"] is None and s["selftest_by_function"] == {"pay_amount": False}


def test_missing_pdoc_is_isolated(env):
    llm = FakeLLM([GOOD_RULES])
    out = pipeline.run_pdfs(
        None,
        "run3",
        env["corpus"],
        env["rev"],
        ["doc-a", "doc-missing"],
        k_shots_text="",
        d_shots_text="",
        cfg=env["cfg"],
        llm=llm,
    )
    assert out["doc-missing"]["error"].startswith("load:")
    assert out["doc-a"]["selftest_by_function"] == {"pay_amount": True}


def test_no_ledger_without_connection(env, monkeypatch):
    called = []
    monkeypatch.setattr(pipeline.sf, "record", lambda *a, **k: called.append(a))
    _run(env, FakeLLM([GOOD_RULES]))
    assert called == []


def test_k_env_override():
    cfg = pipeline.load_cfg(env={"JPCALC_K_PROMPT": "k_cards_x", "JPCALC_K_REPAIR": "0"})
    assert cfg.k.prompt == "k_cards_x" and cfg.k.repair is False
    base = pipeline.load_cfg(env={})
    assert base.k.prompt == "k_cards_p1"


def test_score_selftest_report_mode_ignores_crosscheck():
    fails = [
        {"layer": "crosscheck", "function": "f", "msg": "x"},
        {"layer": "example", "function": "g", "msg": "y"},
    ]
    r = pipeline.score_selftest({"f": False, "g": False, "h": True}, fails, [], "report")
    assert r["by_function"] == {"f": True, "g": False, "h": True}
    assert r["n_fail_functions"] == 1 and all(
        f["layer"] != "crosscheck" for f in r["fails_for_repair"]
    )


def test_pick_best_prefers_earlier_on_tie():
    h = [
        {"iteration": 0, "module": "a", "n_fail_functions": 1, "score": 1},
        {"iteration": 1, "module": "b", "n_fail_functions": 1, "score": 1},
        {"iteration": 2, "module": None, "n_fail_functions": 0, "score": 0},
    ]
    assert pipeline.pick_best(h)["iteration"] == 0


def test_tuning_empty_is_identical_and_nonempty_is_applied(env, monkeypatch):
    """tuning:（コーパスの設定）：空なら今と同じ出力・同じ要求。値があれば予測の間だけ読み出し口に当たり、
    summary に SHA-256 が残る。"""
    from jpcalc.common.tunables import tun

    def prompts(llm):
        return [c for c in llm.calls]

    a, b = FakeLLM([GOOD_RULES]), FakeLLM([GOOD_RULES])
    s0 = _run(env, a)["doc-a"]
    s1 = pipeline.run_pdfs(
        None,
        "run1",
        env["corpus"],
        env["rev"],
        ["doc-a"],
        k_shots_text="",
        d_shots_text="",
        cfg=env["cfg"],
        llm=b,
        tuning={},
    )["doc-a"]
    assert s0 == s1 and prompts(a) == prompts(b) and "tuning_sha256" not in s1

    seen = []
    real = pipeline.run_docs

    def spy(*args, **kw):
        seen.append(tun("j1.title_cues", ()))
        return real(*args, **kw)

    monkeypatch.setattr(pipeline, "run_docs", spy)
    s2 = pipeline.run_pdfs(
        None,
        "run2",
        env["corpus"],
        env["rev"],
        ["doc-a"],
        k_shots_text="",
        d_shots_text="",
        cfg=env["cfg"],
        llm=FakeLLM([GOOD_RULES]),
        tuning={"j1.title_cues": ["期限"]},
    )["doc-a"]
    assert seen == [["期限"]] and len(s2["tuning_sha256"]) == 64
    assert tun("j1.title_cues", ()) == ()  # 文脈の外では効かない


def test_corpus_tuning_validation(tmp_path):
    import shutil

    import yaml

    from jpcalc.common.paths import CORPORA
    from jpcalc.config import ConfigError, load_corpus_config

    assert load_corpus_config("contract").tuning == {}
    shutil.copy(CORPORA / "contract.yaml", tmp_path / "contract.yaml")
    y = yaml.safe_load((tmp_path / "contract.yaml").read_text(encoding="utf-8"))
    y["tuning"] = {"j1.title_cues": ["期限", "喪失"]}
    (tmp_path / "contract.yaml").write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
    assert load_corpus_config("contract", tmp_path).tuning == {"j1.title_cues": ["期限", "喪失"]}
    y["tuning"] = {"j1.nope": ["x"]}
    (tmp_path / "contract.yaml").write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_corpus_config("contract", tmp_path)

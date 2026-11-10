"""予測のパイプライン：pdoc → K（規定の発見とカード）→ D（計算仕様）→ T（設例・検算）→ I → T（自己テスト）→ R。

入力は pdoc（out/<corpus>/<rev>/pdoc/<pdf_id>.json）だけ。正解（answers/・calc/・layout.json）を開かない。
出力は out/<corpus>/<rev>/runs/<run_id>/<pdf_id>/ に、カード・仕様・Python・自己テスト・summary を書く。
AI の呼び出しは LLM（作業スキーマの要求表 → 運用スキーマのプロシージャ → キャッシュ表）を通す。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from ..common import sf
from ..common.paths import OUT
from ..common.tunables import override
from ..config import PipelineCfg, load_pipeline_config
from . import codegen, d_spec, k_cards, k_lint, r_repair, t_crosscheck, t_examples, t_selftest
from . import spec as SP
from .card_schema import check_card
from .llm import LLM
from .policy_index import PolicyIndex

# 試行で K の版と切り替えを上書きする環境変数（値は pipeline.yaml の k に当てる）
_K_ENV = {
    "JPCALC_K_PROMPT": ("prompt", str),
    "JPCALC_K_RESCAN": ("rescan", bool),
    "JPCALC_K_RESCAN_PROMPT": ("rescan_prompt", str),
    "JPCALC_K_REPAIR": ("repair", bool),
    "JPCALC_K_REPAIR_PROMPT": ("repair_prompt", str),
}


def load_cfg(env: dict[str, str] | None = None) -> PipelineCfg:
    """configs/pipeline.yaml に環境変数の上書きを当てた、実際に使う設定。"""
    env = os.environ if env is None else env
    cfg = load_pipeline_config()
    upd: dict = {}
    for name, (key, typ) in _K_ENV.items():
        v = env.get(name)
        if typ is bool and v in ("0", "1"):
            upd[key] = v == "1"
        elif typ is str and v:
            upd[key] = v
    return cfg.model_copy(update={"k": cfg.k.model_copy(update=upd)}) if upd else cfg


def pdoc_dir(corpus: str, rev: str) -> Path:
    return OUT / corpus / rev / "pdoc"


def run_dir(corpus: str, rev: str, run_id: str, pdf_id: str) -> Path:
    d = OUT / corpus / rev / "runs" / run_id / pdf_id
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class DocState:
    doc_id: str
    cards: list[dict]
    ix: PolicyIndex
    ctx: dict | None = None
    j: dict = field(default_factory=dict)
    examples: list[dict] = field(default_factory=list)
    example_errors: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    spec: dict | None = None
    spec_probs: list[str] = field(default_factory=list)
    raw_answer: dict | None = None
    done: bool = False
    error: str | None = None


def load_states(
    corpus: str, rev: str, pdf_ids: list[str], src_dir: Path | None = None
) -> dict[str, DocState]:
    """pdoc を読む。読めない PDF は error を持つ状態にして、ほかの PDF は続ける。"""
    src_dir = src_dir or pdoc_dir(corpus, rev)
    st: dict[str, DocState] = {}
    for d in pdf_ids:
        try:
            doc = json.loads((src_dir / f"{d}.json").read_text(encoding="utf-8"))
            st[d] = DocState(d, [], PolicyIndex(doc))
        except Exception as e:  # noqa: BLE001
            st[d] = DocState(d, [], PolicyIndex({}), error=f"load: {type(e).__name__}: {e}")
    return st


def run_docs(
    llm,
    states: dict[str, DocState],
    cfg: PipelineCfg,
    *,
    k_shots_text: str,
    d_shots_text: str,
    max_iter: int | None = None,
) -> None:
    """各 DocState に K の結果・仕様の周回の記録（history）を入れる。書き出しは finalize が行う。"""
    model = cfg.llm.model
    mt = cfg.llm.max_tokens
    max_iter = cfg.repair.max_iter if max_iter is None else max_iter
    live = [s for s in states.values() if not s.error]

    # ---- K：規定の発見とカードの合成（再走査・点検・K-R を含む）
    k_cards.run(
        llm,
        live,
        model=model,
        max_tokens=mt.k_cards,
        rescan=cfg.k.rescan,
        version=cfg.k.prompt,
        rescan_version=cfg.k.rescan_prompt,
        repair=cfg.k.repair,
        repair_version=cfg.k.repair_prompt,
        shots_text=k_shots_text,
    )
    live = [s for s in live if not s.error]

    # ---- D（初回）
    reqs = [
        d_spec.make_request(
            s.doc_id, s.ctx, s.cards, model=model, max_tokens=mt.d_spec, shots_text=d_shots_text
        )
        for s in live
    ]
    for s, resp in zip(live, llm.complete(reqs), strict=True):
        _take_answer(s, resp, 0)

    # ---- T 層 2 の種（設例）
    ex_reqs, ex_docs = [], []
    for s in live:
        paras = t_examples.example_paragraphs(s.ix, s.ctx["containers"])
        r = t_examples.make_request(s.doc_id, paras, s.cards, model=model, max_tokens=mt.t_examples)
        if r:
            ex_reqs.append(r)
            ex_docs.append(s)
    for s, resp in zip(ex_docs, llm.complete(ex_reqs), strict=True):
        if resp.ok:
            s.examples, s.example_errors = t_examples.to_cases(resp.parsed, s.cards)
        else:
            s.example_errors = [f"llm: {resp.err}"]

    # ---- T 層 4 の種（独立の検算。初回の仕様の境界点を、仕様を見せずに文書だけで計算させる）
    if cfg.selftest.crosscheck_points > 0:
        x_reqs, x_docs = [], []
        for s in live:
            if s.spec is None:
                continue
            sub, _ = (
                d_spec.usable_subset(s.spec, s.cards, s.spec_probs)
                if s.spec_probs
                else (s.spec, [])
            )
            if sub is None:
                continue
            cases = t_crosscheck.pick_cases(
                sub, s.cards, per_function=cfg.selftest.crosscheck_points
            )
            r = t_crosscheck.make_request(
                s.doc_id, s.ctx, s.cards, cases, model=model, max_tokens=mt.t_crosscheck
            )
            if r:
                x_reqs.append(r)
                x_docs.append((s, cases))
        for (s, cases), resp in zip(x_docs, llm.complete(x_reqs), strict=True):
            if resp.ok:
                s.examples += t_crosscheck.to_examples(resp.parsed, cases, s.cards)

    # ---- I → T → R の周回
    for it in range(max_iter + 1):
        todo = []
        for s in live:
            if s.done:
                continue
            rec = _implement_and_test(s, it, cfg)
            s.history.append(rec)
            if rec["n_fail_functions"] == 0 or it == max_iter or not rec["repairable"]:
                s.done = True
            else:
                todo.append((s, rec))
        if not todo:
            break
        reqs = [
            r_repair.make_request(
                s.doc_id,
                s.ctx,
                s.cards,
                s.raw_answer or {"rules": []},
                rec["fails_for_repair"],
                model=model,
                max_tokens=mt.r_repair,
                iteration=it + 1,
            )
            for s, rec in todo
        ]
        for (s, _), resp in zip(todo, llm.complete(reqs), strict=True):
            _take_answer(s, resp, it + 1)


def _take_answer(s: DocState, resp, iteration: int) -> None:
    if not resp.ok:
        s.spec, s.spec_probs = None, [f"llm: {resp.err}"]
        return
    s.raw_answer = resp.parsed if isinstance(resp.parsed, dict) else {"rules": []}
    try:
        s.spec, s.spec_probs = d_spec.assemble(s.doc_id, s.raw_answer, s.ctx, s.cards)
    except Exception as e:  # noqa: BLE001
        s.spec, s.spec_probs = None, [f"assemble: {type(e).__name__}: {e}"]


def _implement_and_test(s: DocState, it: int, cfg: PipelineCfg) -> dict:
    rec = {
        "iteration": it,
        "spec": s.spec,
        "spec_probs": list(s.spec_probs),
        "spec_warnings": SP.warnings(s.spec) if s.spec else [],
        "module": None,
        "selftest": None,
    }
    fns = [c["function"] for c in s.cards]
    check_fails = [{"layer": "check", "function": None, "msg": p} for p in s.spec_probs[:20]]
    spec = s.spec
    dropped: list[str] = []
    if spec is not None and s.spec_probs:
        spec, dropped = d_spec.usable_subset(spec, s.cards, s.spec_probs)
    if spec is None:
        rec.update(
            n_fail_functions=len(fns),
            by_function={f: False for f in fns},
            fails_for_repair=check_fails,
            repairable=s.raw_answer is not None or bool(s.spec_probs),
        )
        return rec
    rec["dropped"] = dropped
    try:
        src = codegen.generate(spec)
    except Exception as e:  # noqa: BLE001
        fails = [{"layer": "check", "function": None, "msg": f"codegen: {e}"}]
        rec.update(
            n_fail_functions=len(fns),
            by_function={f: False for f in fns},
            fails_for_repair=fails,
            repairable=True,
        )
        return rec
    rec["module"] = src
    kept = [c for c in s.cards if c["function"] not in dropped]
    tr = t_selftest.run(
        spec,
        src,
        kept,
        [e for e in s.examples if e["function"] not in dropped],
        n_random=cfg.selftest.random_cases,
        deltas=tuple(cfg.selftest.boundary_delta),
        timeout=cfg.sandbox.timeout_sec,
        per_call_timeout=cfg.sandbox.per_call_timeout_sec,
    )
    rec["selftest"] = tr
    fails = check_fails + tr["fails"]
    rec["crosscheck_suspects"] = sorted(
        {f["function"] for f in fails if f["layer"] == "crosscheck"}
    )
    rec.update(score_selftest(tr["by_function"], fails, dropped, cfg.selftest.crosscheck_mode))
    return rec


def score_selftest(
    selftest_by_function: dict[str, bool],
    fails: list[dict],
    dropped: list[str],
    crosscheck_mode: str,
) -> dict:
    """自己検査の結果から、関数ごとの合否・改修に渡す失敗・周回の点数を決める（純関数）。

    - 使えずに落とした関数（dropped）は不合格。
    - report：検算（層 4）の不一致は疑いとして残すだけで、合否と改修には使わない。
    - repair：検算だけで落ちた関数は「疑い」（crosscheck_only）。別の担当者の読みとの食い違いで、文書が支持する側は
      分からないので、最終版の選択では 0.5 件と数える（同点なら前の周回を残す。D の明示の判断を検算だけで覆さない）。
    """
    by_function = dict(selftest_by_function) | {f: False for f in dropped}
    hard = {f["function"] for f in fails if f["layer"] != "crosscheck"}  # 検算以外の層で落ちた関数
    if crosscheck_mode == "report":
        by_function = {
            f: (ok or f not in hard) and f not in dropped for f, ok in by_function.items()
        }
        fails = [f for f in fails if f["layer"] != "crosscheck"]
    bad = [f for f, ok in by_function.items() if not ok]
    soft = [f for f in bad if f not in hard and f not in dropped]
    return {
        "n_fail_functions": len(bad),
        "score": len(bad) - 0.5 * len(soft),
        "by_function": by_function,
        "fails_for_repair": fails,
        "repairable": r_repair.needs_d_repair(fails),
        "crosscheck_only": soft,
    }


def pick_best(history: list[dict]) -> dict | None:
    """モジュールが作れた周回のうち点数の最も良いもの（同点なら前の周回）。"""
    best = None
    for rec in history:
        if rec["module"] and (
            best is None
            or rec.get("score", rec["n_fail_functions"])
            < best.get("score", best["n_fail_functions"])
        ):
            best = rec
    return best


def _write_json(path: Path, obj, **kw) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, **kw), encoding="utf-8")


def finalize(s: DocState, d: Path, tuning_sha256: str | None = None) -> dict:
    """1 PDF の生成物を d に書き、summary を返す。tuning を当てた run は、その SHA-256 を summary に書く。"""
    summary = {
        "doc_id": s.doc_id,
        "error": s.error,
        "example_errors": s.example_errors,
        "n_examples": len(s.examples),
        "iterations": len(s.history),
        "j": s.j,
    }
    if tuning_sha256:
        summary["tuning_sha256"] = tuning_sha256
    for rec in s.history:
        it = rec["iteration"]
        _write_json(d / f"spec_iter{it}.json", rec["spec"], indent=1, default=str)
        if rec["module"]:
            (d / f"module_iter{it}.py").write_text(rec["module"], encoding="utf-8")
        _write_json(
            d / f"selftest_iter{it}.json",
            {
                k: rec[k]
                for k in ("spec_probs", "n_fail_functions", "by_function", "fails_for_repair")
            }
            | {
                "spec_warnings": rec.get("spec_warnings", []),
                "stats": (rec["selftest"] or {}).get("stats"),
            },
            indent=1,
            default=str,
        )
    best = pick_best(s.history)
    # 合成カード。採点側の対応付け M が読む
    (d / "cards.jsonl").write_text(
        "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in s.cards), encoding="utf-8"
    )
    summary["cards"] = "cards.jsonl"
    # カードは採点側との契約。schema に合わない点は捨てずに記録する
    summary["card_schema_errors"] = [e for c in s.cards for e in check_card(c)]
    # 呼び出し口の点検（決定的）。旗は別ファイルに置き、カードと下流の要求は変えない
    lint = k_lint.lint_cards(s.cards)
    _write_json(d / "k_lint.json", lint, indent=1)
    summary["k_lint"] = {"n_flagged": lint["n_flagged"], "counts": lint["counts"]}
    _write_json(d / "examples.json", s.examples, indent=1, default=str)
    if best:
        mod = d / f"calc_{s.doc_id.replace('-', '_')}.py"
        mod.write_text(best["module"], encoding="utf-8")
        summary.update(
            final_iteration=best["iteration"],
            selftest_by_function=best["by_function"],
            module=mod.name,
            crosscheck_suspects=best.get("crosscheck_suspects", []),
        )
    else:
        summary.update(
            final_iteration=None,
            selftest_by_function={c["function"]: False for c in s.cards},
            module=None,
        )
    summary["history"] = [
        {
            "iteration": r["iteration"],
            "n_fail_functions": r["n_fail_functions"],
            "score": r.get("score"),
            "crosscheck_only": r.get("crosscheck_only"),
            "n_spec_probs": len(r["spec_probs"]),
            "n_spec_warnings": len(r.get("spec_warnings") or []),
        }
        for r in s.history
    ]
    _write_json(d / "summary.json", summary, indent=1, default=str)
    return summary


def run_pdfs(
    conn,
    run_id: str,
    corpus: str,
    rev: str,
    pdf_ids: list[str],
    *,
    k_shots_text: str,
    d_shots_text: str,
    cfg: PipelineCfg | None = None,
    llm=None,
    max_iter: int | None = None,
    step: str = "P",
    tuning: dict | None = None,
) -> dict[str, dict]:
    """pdf_ids をまとめて予測し、PDF ごとの summary を返す。conn があれば台帳（STEP_RUNS）に記録する。

    tuning：コーパスの設定の tuning:（読み出し口の値）。空なら今の動作のまま。当てたときは summary に
    その SHA-256 を記録する（出所）。
    """
    cfg = cfg or load_cfg()
    llm = llm or LLM(conn, run_id)
    tuning = dict(tuning or {})
    states = load_states(corpus, rev, pdf_ids)
    with override(tuning, strict=False) if tuning else contextlib.nullcontext():
        run_docs(
            llm,
            states,
            cfg,
            k_shots_text=k_shots_text,
            d_shots_text=d_shots_text,
            max_iter=max_iter,
        )
    t_sha = (
        hashlib.sha256(json.dumps(tuning, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if tuning
        else None
    )
    out: dict[str, dict] = {}
    for d, s in states.items():
        rd = run_dir(corpus, rev, run_id, d)
        summary = finalize(s, rd, tuning_sha256=t_sha)
        out[d] = summary
        if conn is not None:
            try:
                ok = summary["module"] is not None
                sf.record(
                    conn,
                    run_id,
                    step,
                    d,
                    "SUCCEEDED" if ok else "FAILED",
                    n_errors=sum(1 for v in summary["selftest_by_function"].values() if not v),
                    error_text=s.error or (None if ok else "; ".join(s.spec_probs)[:4000]),
                    output_uri=str(rd),
                    detail={k: summary[k] for k in ("final_iteration", "iterations", "n_examples")},
                )
            except Exception:  # noqa: BLE001  台帳の書き込み失敗は生成物を失わせない（ログに残す）
                traceback.print_exc()
    out["_llm_stats"] = dict(getattr(llm, "stats", {}))
    return out

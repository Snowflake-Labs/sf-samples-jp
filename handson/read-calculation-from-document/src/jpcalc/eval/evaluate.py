"""採点（段 E）：生成物を対応付け M のアダプタ越しに正解テストで採点し、集計する（評価側だけ）。

評価側だけが正解（カード・answer_key・cases・テスト）を読む。生成物は予測の出力の置き場所
（<run_dir>/<pdf_id>/：summary.json・cards.jsonl・calc_*.py・spec_iter<N>.json）から読み、書き込まない。
対応付けとアダプタは評価側の作業場所に書く。
生成物の置き場所は予測側が書けるので、予測側の書いた Python はそのまま採点しない。最終の周回の計算仕様から
codegen で作り直し、予測側の Python と AST（docstring を除く）で一致したときだけ、作り直したものを採点する。
実装できなかったルール（対応なし・モジュールなし・生成の失敗）は不合格として数え、分母から外さない。

主指標：正解ルール×PDF のうち、対応が付き、正解の全ケースに合格したルールの割合。
診断（主指標に使わない）：生成側にだけある引数を「該当しない」で補った場合／None を明示した場合の合格数。
"""

from __future__ import annotations

import ast
import collections
import json
import re
from pathlib import Path

from ..predict import codegen, idents
from ..predict.codegen_check import check_module
from . import match, score
from .gold import Gold

SPLIT_ROUND = 4
# summary.json が指してよいファイルの名前（予測側が書く値なので、置き場所の外を指させない）
MODULE_NAME = re.compile(r"^calc_[A-Za-z0-9_]{1,200}\.py$")
CARDS_NAME = "cards.jsonl"


def strip_docstrings(tree: ast.Module) -> ast.Module:
    """モジュールと関数の先頭の docstring を外す（コメントは AST に入らない）。比較だけに使う。"""
    for n in [tree, *ast.walk(tree)]:
        body = getattr(n, "body", None)
        if (
            isinstance(n, ast.Module | ast.FunctionDef)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            n.body = body[1:] or [ast.Pass()]
    return tree


def regenerate(spec: dict, module_src: str) -> tuple[str | None, str | None]:
    """予測側の Python を、計算仕様から作り直したものに置き換える。戻り値：(作り直したソース, 問題)。

    予測側は使えない関数を外して生成する（usable_subset）ので、モジュールが定義する関数だけで作り直す。
    モジュールにある関数が仕様に無い、作り直せない、AST（docstring を除く）が一致しない、のどれかなら問題を返す。
    """
    try:
        tree = ast.parse(module_src)
    except (SyntaxError, ValueError):
        return None, "regenerated_mismatch: the module does not parse"
    defined = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    rules = [r for r in (spec or {}).get("rules") or [] if isinstance(r, dict)]
    keep = [r for r in rules if r.get("function") in defined]
    extra = sorted(set(defined) - {r.get("function") for r in keep} - idents.reserved())
    if extra:
        return None, f"regenerated_mismatch: functions not in the spec {extra[:3]}"
    try:
        src = codegen.generate(dict(spec, rules=keep))
    except Exception as e:  # noqa: BLE001  作り直せない仕様は採点しない
        return None, f"regenerated_mismatch: codegen failed ({type(e).__name__})"
    if ast.dump(strip_docstrings(ast.parse(src))) != ast.dump(strip_docstrings(tree)):
        return (
            None,
            "regenerated_mismatch: the module differs from the code generated from the spec",
        )
    return src, None


def _path_problem(summ: dict) -> str | None:
    mod, cards = summ.get("module"), summ.get("cards")
    if mod is not None and not (isinstance(mod, str) and MODULE_NAME.match(mod)):
        return f"bad_path: module {str(mod)[:80]!r}"
    if cards is not None and cards != CARDS_NAME:
        return f"bad_path: cards {str(cards)[:80]!r}"
    it = summ.get("final_iteration")
    if it is not None and (isinstance(it, bool) or not isinstance(it, int) or it < 0):
        return f"bad_path: final_iteration {it!r}"
    return None


def _final_spec(gen_dir: Path, summ: dict) -> dict | None:
    it = summ.get("final_iteration")
    p = gen_dir / f"spec_iter{it}.json"
    if it is None or not p.is_file():
        return None
    obj = json.loads(p.read_text(encoding="utf-8"))
    return obj if isinstance(obj, dict) else None


def _median(xs) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    mid = len(v) // 2
    return round(v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2, SPLIT_ROUND)


def _rate(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), SPLIT_ROUND) if xs else None


def _score_with(g: Gold, pdf_id: str, src: str, mp: dict, work: Path, name: str, fill=None) -> dict:
    ad = work / name
    ad.write_text(match.adapter_source(src, mp, fill_extra=fill), encoding="utf-8")
    return score.summarize(g, pdf_id, score.run_pytest(g, ad))


def evaluate_pdf(g: Gold, pdf_id: str, gen_dir: Path, work: Path) -> tuple[list[dict], dict]:
    """1 PDF を採点する。戻り値：(ルールの行, 文書の行)。"""
    work.mkdir(parents=True, exist_ok=True)
    gold_cards = g.task_cards()
    summ_p = gen_dir / "summary.json"
    summ = json.loads(summ_p.read_text(encoding="utf-8")) if summ_p.exists() else {}
    summ = summ if isinstance(summ, dict) else {}
    bad_path = _path_problem(summ)
    gen_cards = (
        match.load_cards_file(gen_dir / summ["cards"])
        if not bad_path and summ.get("cards") and (gen_dir / summ["cards"]).exists()
        else []
    )
    gtext = match.gold_evidence(gold_cards, g.answer_key(), g.text_json())
    mp = match.build_map(pdf_id, gold_cards, gtext, gen_cards)
    (work / "_match.json").write_text(
        json.dumps(mp, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    mod = gen_dir / summ["module"] if summ.get("module") and not bad_path else None
    diag_neutral: dict[str, bool] = {}
    diag_none: dict[str, bool] = {}
    # 生成物のステージは予測側が書ける。正解テストと同じプロセスで動かす前に、(1) 予測側の Python の静的検査、
    # (2) 最終の周回の仕様からの作り直しと AST の照合、(3) 作り直したものの静的検査を通す。
    # 採点するのは作り直したソースだけ。どれかに落ちれば不合格として数える
    problems: list[str] = [bad_path] if bad_path else []
    src = None
    if not problems and mod is not None and mod.exists():
        raw = mod.read_text(encoding="utf-8")
        problems = check_module(raw)
        if not problems:
            spec = _final_spec(gen_dir, summ)
            src, prob = regenerate(spec, raw) if spec is not None else (None, "no_spec")
            problems = [prob] if prob else check_module(src)
    if src is not None and not problems:
        sm = _score_with(g, pdf_id, src, mp, work, "_adapter.py")
        if mp["functions"]:
            dn = _score_with(
                g, pdf_id, src, mp, work, "_adapter_neutral.py", match.neutral_fill(mp, gen_cards)
            )
            diag_neutral = {r["function"]: r["passed"] for r in dn["rules"]}
            dz = _score_with(g, pdf_id, src, mp, work, "_adapter_none.py", match.none_fill(mp))
            diag_none = {r["function"]: r["passed"] for r in dz["rules"]}
    else:
        reason = (
            "unsafe_module: " + "; ".join(problems[:3])
            if problems
            else "no_module"
            if summ
            else "no_output"
        )
        sm = score.summarize(g, pdf_id, score.no_module(g, reason))
    st = summ.get("selftest_by_function") or {}
    fsc = {d["gold"]: d for d in mp["function_scores"]}
    for r in sm["rules"]:
        m = mp["functions"].get(r["function"])
        r["matched_gen"] = m["gen"] if m else None
        r["evidence_gen_precision"] = (fsc.get(r["function"]) or {}).get("gen_precision")
        r["evidence_length_ratio"] = (fsc.get(r["function"]) or {}).get("length_ratio")
        r["args_complete"] = bool(m) and not m["unmapped_gold_args"]
        r["extra_gen_args"] = len(m["extra_gen_args"]) if m else 0
        r["selftest_passed"] = bool(m) and bool(st.get(m["gen"]))
        r["passed_neutral_fill"] = diag_neutral.get(r["function"], False)
        r["passed_without_omitted"] = diag_none.get(r["function"], False)
    man = g.manifest()
    doc = {
        "pdf_id": pdf_id,
        "error": sm["error"] or summ.get("error"),
        "n_cases": sm["n_cases"],
        "n_pass": sm["n_pass"],
        "n_gen": mp["n_gen"],
        "n_gold": mp["n_gold"],
        "n_matched": len(mp["functions"]),
        "extra_gen": mp["extra_gen"],
        "profile": man.get("profile"),
    }
    return sm["rules"], doc


def lost_stage(r: dict) -> str | None:
    """不合格のルールの段ごとの帰属。生成側にだけある引数で落ちたものは呼び出し口の差として数える。"""
    if r["passed"]:
        return None
    if not r.get("matched_gen"):
        return "not_found"
    if not r.get("args_complete"):
        return "interface"
    if r.get("extra_gen_args"):
        return "interface_extra_args"
    return "calculation"


def aggregate(rules: list[dict], docs: list[dict], meta: dict[str, dict]) -> dict:
    """集計と内訳。meta は PDF ごとの公開の属性（stratum・style）。"""
    by: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    case_kind: dict = collections.defaultdict(lambda: [0, 0])
    prof = {d["pdf_id"]: d.get("profile") for d in docs}
    for r in rules:
        p = r["passed"]
        m = meta.get(r["pdf_id"], {})
        by["pattern"][str(r["pattern"])].append(p)
        by["placement"][r["placement"]].append(p)
        by["profile"][str(prof.get(r["pdf_id"]))].append(p)
        by["stratum"][str(m.get("stratum"))].append(p)
        by["style"][str(m.get("style"))].append(p)
        by["figure_only"][str(r["figure_only"])].append(p)
        for mo in r["modalities"]:
            by["modality"][mo].append(p)
        for k, v in (r["difficulty"] or {}).items():
            by["difficulty"][k if v is True else f"{k}={v}"].append(p)
        by["selftest"]["pass" if r["selftest_passed"] else "fail"].append(p)
        for k, (ok, n) in r["by_kind"].items():
            case_kind[k][0] += ok
            case_kind[k][1] += n
    n_gold = sum(d["n_gold"] for d in docs)
    n_gen = sum(d["n_gen"] for d in docs)
    n_m = sum(d["n_matched"] for d in docs)
    matched = [r for r in rules if r.get("matched_gen")]
    lost = collections.Counter(s for s in map(lost_stage, rules) if s)
    n_cases = sum(d["n_cases"] for d in docs)
    n_pass = sum(d["n_pass"] for d in docs)
    return {
        "n_pdfs": len(docs),
        "n_rules": len(rules),
        "n_rules_pass": sum(r["passed"] for r in rules),
        "rule_pass_rate": _rate(r["passed"] for r in rules),
        "n_cases": n_cases,
        "n_cases_pass": n_pass,
        "case_accuracy": round(n_pass / n_cases, SPLIT_ROUND) if n_cases else None,
        "n_errors": sum(1 for d in docs if d["error"]),
        "coverage": _rate(d["error"] not in ("no_module", "no_output") for d in docs),
        "selftest_missed": sum(1 for r in rules if r["selftest_passed"] and not r["passed"]),
        "discovery": {
            "n_gold_rules": n_gold,
            "n_gen_functions": n_gen,
            "n_matched": n_m,
            "recall": round(n_m / n_gold, SPLIT_ROUND) if n_gold else None,
            "precision": round(n_m / n_gen, SPLIT_ROUND) if n_gen else None,
            "interface_complete": _rate(r["args_complete"] for r in matched),
            "interface_exact": _rate(
                r["args_complete"] and not r["extra_gen_args"] for r in matched
            ),
            "pass_given_matched": _rate(r["passed"] for r in matched),
            "lost_by_stage": dict(lost),
            "n_extra_gen": sum(len(d["extra_gen"]) for d in docs),
        },
        "diagnostics": {
            "pass_neutral_fill": sum(r["passed_neutral_fill"] for r in rules),
            "pass_without_omitted": sum(r["passed_without_omitted"] for r in rules),
            # 対応した組の根拠の診断（主指標と対応付けには使わない。README §15 の採点の限界）
            "evidence_gen_precision_median": _median(
                r.get("evidence_gen_precision") for r in matched
            ),
            "evidence_length_ratio_median": _median(
                r.get("evidence_length_ratio") for r in matched
            ),
            "n_matched_gen_precision_below_half": sum(
                (r.get("evidence_gen_precision") or 0) < 0.5 for r in matched
            ),
        },
        "breakdown": {
            k: {kk: {"n": len(v), "pass": sum(v), "rate": _rate(v)} for kk, v in sorted(g.items())}
            for k, g in by.items()
        },
        "by_case_kind": {
            k: {"pass": ok, "n": n, "rate": round(ok / n, SPLIT_ROUND) if n else None}
            for k, (ok, n) in sorted(case_kind.items())
        },
        "rules": rules,
        "docs": docs,
    }


def evaluate_run(
    corpus: str,
    gold_root: Path,
    run_dir: Path,
    pdf_ids: list[str],
    work_dir: Path,
    meta: dict[str, dict] | None = None,
) -> dict:
    """run の PDF をすべて採点する。run_dir は <出力>/runs/<run_id>（PDF ごとの生成物の親）。"""
    rules: list[dict] = []
    docs: list[dict] = []
    for pdf in pdf_ids:
        g = Gold(corpus, gold_root, pdf)
        rs, d = evaluate_pdf(g, pdf, run_dir / pdf, work_dir / pdf)
        rules += rs
        docs.append(d)
    return {"corpus": corpus, **aggregate(rules, docs, meta or {})}

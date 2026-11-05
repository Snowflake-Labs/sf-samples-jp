"""評価結果の台帳への書き込みと退避（評価側だけ。評価ロールで接続する）。

EVAL_RUNS（1 評価 1 行。集計と内訳の summary）と RULE_RESULTS（正解ルール×PDF の 1 行）を
1 つのトランザクションで書く（片方だけの記録を残さない）。退避は 2 表を run 単位で JSON Lines に書き、
書いた行数と表の行数を照合する。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..common import sf
from .evaluate import lost_stage

RULE_COLS = (
    "pdf_id", "function", "rule", "pattern", "passed", "n_cases", "n_pass", "by_kind", "modalities",
    "difficulty", "figure_only", "placement", "selftest_passed", "matched_gen", "args_complete",
    "extra_gen_args", "lost_stage", "passed_neutral_fill", "passed_without_omitted",
)  # fmt: skip


def _t(obj: str) -> str:
    return sf.names().fq("schema_results", obj)


def rule_rows(res: dict) -> list[dict]:
    return [
        {k: (lost_stage(r) if k == "lost_stage" else r.get(k)) for k in RULE_COLS}
        for r in res["rules"]
    ]


def write_db(conn, res: dict, *, eval_run_id: str, image_tag: str | None) -> int:
    summary = {k: v for k, v in res.items() if k not in ("rules", "docs")} | {"docs": res["docs"]}
    rows = rule_rows(res)
    sf.query(conn, "BEGIN")
    try:
        sf.query(conn, f"DELETE FROM {_t('RULE_RESULTS')} WHERE eval_run_id = %s", (eval_run_id,))
        sf.query(conn, f"DELETE FROM {_t('EVAL_RUNS')} WHERE eval_run_id = %s", (eval_run_id,))
        sf.query(
            conn,
            f"""INSERT INTO {_t("EVAL_RUNS")} (eval_run_id, run_id, corpus, dataset_revision, image_tag,
              n_pdfs, n_rules, n_rules_pass, n_cases, n_cases_pass, n_errors, summary, created_at)
            SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), CURRENT_TIMESTAMP()""",
            (
                eval_run_id, res["run_id"], res["corpus"], res["dataset_revision"], image_tag,
                res["n_pdfs"], res["n_rules"], res["n_rules_pass"], res["n_cases"], res["n_cases_pass"],
                res["n_errors"], json.dumps(summary, ensure_ascii=False, default=str),
            ),
        )  # fmt: skip
        sel = ", ".join(
            f"v.value:{c}" + ("" if c in ("by_kind", "difficulty") else "::ARRAY" if c == "modalities" else
                              "::BOOLEAN" if c in ("passed", "figure_only", "selftest_passed", "args_complete",
                                                   "passed_neutral_fill", "passed_without_omitted") else
                              "::INT" if c in ("n_cases", "n_pass", "extra_gen_args") else "::STRING")
            for c in RULE_COLS
        )  # fmt: skip
        sf.query(
            conn,
            f"""INSERT INTO {_t("RULE_RESULTS")} (eval_run_id, run_id, {", ".join(RULE_COLS)})
            SELECT %s, %s, {sel} FROM TABLE(FLATTEN(input => PARSE_JSON(%s))) v""",
            (eval_run_id, res["run_id"], json.dumps(rows, ensure_ascii=False, default=str)),
        )
        sf.query(conn, "COMMIT")
    except Exception:
        sf.query(conn, "ROLLBACK")
        raise
    return len(rows)


def export(conn, run_id: str | None, dest_root: Path) -> list[dict]:
    """run の評価記録を results/<run_id>__<eval_run_id>/ に退避し、行数を照合する。"""
    out = []
    evs = sf.query(
        conn,
        f"SELECT eval_run_id, run_id FROM {_t('EVAL_RUNS')} "
        + ("WHERE run_id = %s " if run_id else "")
        + "ORDER BY eval_run_id",
        (run_id,) if run_id else None,
    )
    for e in evs:
        eid = e["eval_run_id"]
        d = dest_root / f"{e['run_id']}__{eid}"
        d.mkdir(parents=True, exist_ok=True)
        counts = {}
        for tbl in ("EVAL_RUNS", "RULE_RESULTS", "EVAL_JOBS"):
            rows = sf.query(conn, f"SELECT * FROM {_t(tbl)} WHERE eval_run_id = %s", (eid,))
            p = d / f"{tbl.lower()}.jsonl"
            p.write_text(
                "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
                encoding="utf-8",
            )
            n_file = sum(1 for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
            n_tbl = sf.query(
                conn, f"SELECT COUNT(*) AS n FROM {_t(tbl)} WHERE eval_run_id = %s", (eid,)
            )[0]["n"]
            if n_file != n_tbl:
                raise RuntimeError(
                    f"退避の行数が合わない: {tbl} {eid}: ファイル {n_file}・表 {n_tbl}"
                )
            counts[tbl] = n_tbl
        out.append({"eval_run_id": eid, "dir": str(d), "counts": counts})
    return out


def upload_gold(conn, corpus: str, rev: str, pdf_ids: list[str], eval_root: Path) -> dict:
    """評価に使う正解（照合済みのものだけ）を正解のステージの <corpus>/<rev>/ に同じ配置で置く。

    予測の入力ステージ・生成物のステージには置かない。置く前に照合値で確かめ、未照合のファイルがあれば止める。
    """
    import tempfile

    from ..ops import _put
    from .gold import IDS_FILE, Gold, doc_of, load_ids

    n = sf.names()
    stage = f"@{n.eval_db}.{n.schema_gold}.FILES"
    docs = sorted({doc_of(p) for p in pdf_ids})
    ids = load_ids(eval_root)
    n_files = 0
    keep: dict = {}
    for d in docs:
        g = Gold(corpus, eval_root, d)
        v = g.verify()
        if v["unverified"]:
            raise RuntimeError(f"{d}: 照合値の無い正解は置かない: {v['unverified'][:3]}")
        for f in g.files():
            rel = f.relative_to(eval_root).as_posix()
            _put(conn, f, f"{stage}/{corpus}/{rev}/{Path(rel).parent.as_posix()}/")
            keep[rel] = ids[rel]
            n_files += 1
    with tempfile.TemporaryDirectory(prefix="jpcalc_gold_") as tmp:
        # 置いた正解の照合値だけを置く（ジョブの中でも同じ照合をする）
        p = Path(tmp) / IDS_FILE
        p.write_text(
            json.dumps(keep, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
        )
        _put(conn, p, f"{stage}/{corpus}/{rev}/")
    sf.query(conn, f"ALTER STAGE {n.eval_db}.{n.schema_gold}.FILES REFRESH")
    return {"stage": stage, "n_docs": len(docs), "n_files": n_files}

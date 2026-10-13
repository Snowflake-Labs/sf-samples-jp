"""評価記録と出力 JSON を results/<run_id>/ に書き出す（teardown.sh が DROP の前に呼ぶ）。

run ごとに次を書く（results/ は git 管理外）：
  EVAL_RUNS / DOC_METRICS / PAGE_METRICS / ELEMENT_ERRORS / V_RUN_SUMMARY / V_RUN_SUBSET … 評価側（1 表 1 JSON）
  RUNS / STEP_RUNS                                                                    … 予測側の台帳（その run の行）
  out/<doc_id>.json                                                                   … @OUTPUT.RESULTS/<run_id>/<corpus>/
  EXPORT.json                                                                         … 書き出した件数と DB の件数の照合
書き出した件数が DB の件数と 1 つでも違えば rc=1（teardown はそこで止まり、何も消さない）。
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .common import paths, sf

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

EVAL_TABLES = (
    "EVAL_RUNS",
    "DOC_METRICS",
    "PAGE_METRICS",
    "ELEMENT_ERRORS",
    "V_RUN_SUMMARY",
    "V_RUN_SUBSET",
)
PRED_TABLES = ("RUNS", "STEP_RUNS")


def jsonable(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)  # VARIANT 列はコネクタが JSON 文字列で返す
        except ValueError:
            return v
    return v


def reconcile(counts: dict[str, dict[str, int]]) -> bool:
    """書き出した件数と DB の件数が全表で一致するか。"""
    return all(c["db"] == c["written"] for c in counts.values())


def export_run(conn: SnowflakeConnection, run_id: str, out_root: Path) -> dict:
    n = sf.names()
    dest = out_root / run_id
    (dest / "out").mkdir(parents=True, exist_ok=True)
    counts: dict[str, dict[str, int]] = {}
    for t in EVAL_TABLES + PRED_TABLES:
        fq = n.fq("schema_results", t) if t in EVAL_TABLES else n.fq("schema_ops", t)
        key = "pred_run_id" if t in EVAL_TABLES else "run_id"
        rows = [{k: jsonable(v) for k, v in r.items()}
                for r in sf.query(conn, f"SELECT * FROM {fq} WHERE {key} = %s", (run_id,))]  # fmt: skip
        (dest / f"{t}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        n_db = sf.query(conn, f"SELECT COUNT(*) AS n FROM {fq} WHERE {key} = %s", (run_id,))[0]["n"]
        written = len(json.loads((dest / f"{t}.json").read_text(encoding="utf-8")))
        counts[t] = {"db": int(n_db), "written": written}
    stage = f"@{n.fq('schema_output', 'RESULTS')}/{run_id}/"
    listed = [r for r in sf.query(conn, f"LIST '{stage}'") if r["name"].endswith(".json")]
    if listed:
        sf.query(conn, f"GET '{stage}' 'file://{(dest / 'out').resolve()}/' PATTERN = '.*[.]json'")
    counts["out_json"] = {"db": len(listed), "written": len(list((dest / "out").rglob("*.json")))}
    ok = reconcile(counts)
    record = {"pred_run_id": run_id, "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
              "counts": counts, "ok": ok}  # fmt: skip
    (dest / "EXPORT.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return record


def export_all(run_ids: list[str] | None = None, out_root: Path | None = None) -> int:
    """評価 DB にある全 run（または指定の run）を書き出す。照合が合わなければ 1。"""
    n = sf.names()
    out_root = out_root or (paths.HOME / "results")
    conn = sf.connect(role=n.role_admin)  # 予測側と評価側の両方を読むのはオーナーだけ
    try:
        ids = run_ids or [
            r["pred_run_id"]
            for r in sf.query(
                conn,
                f"SELECT DISTINCT pred_run_id FROM {n.fq('schema_results', 'EVAL_RUNS')} ORDER BY 1",
            )
        ]
        if not ids:
            print("[export] 評価 DB に run が無い。書き出すものは無い", flush=True)
            return 0
        bad = []
        for rid in ids:
            rec = export_run(conn, rid, out_root)
            summary = "・".join(f"{t} {c['written']}" for t, c in rec["counts"].items())
            print(
                f"[export] {rid}: {'ok' if rec['ok'] else '件数が合わない'}（{summary}）",
                flush=True,
            )
            if not rec["ok"]:
                bad.append(rid)
    finally:
        conn.close()
    if bad:
        print(
            f"[export] 件数が DB と合わない run がある（何も消さない）: {bad}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"[export] {len(ids)} run を {out_root} に書き出した", flush=True)
    return 0

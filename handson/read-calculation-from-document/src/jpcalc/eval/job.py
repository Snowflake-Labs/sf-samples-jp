"""SPCS の評価ジョブの入口（`jpcalc job evaluate --run-id ... --eval-run-id ...`）。評価ロールで動く。

マウントするのは次の 2 つだけ（予測の入力ステージはマウントしない）：
  /stage/gold     正解（<corpus>/<rev>/ の下に評価用の置き場所と同じ配置。gold_ids.json を含む）
  /stage/results  生成物（読むだけ。<corpus>/<rev>/runs/<run_id>/<pdf_id>/）
対象は予測の台帳（RUNS）から読む。生成物の無い PDF も分母に入れる（no_output）。結果は評価 DB の表に書く。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

GOLD_ROOT = Path(os.environ.get("JPCALC_STAGE_GOLD", "/stage/gold"))
RESULTS_ROOT = Path(os.environ.get("JPCALC_STAGE_RESULTS", "/stage/results"))


def run_evaluate(run_id: str, eval_run_id: str, *, conn=None) -> dict:
    from ..common import sf
    from ..jobs import load_run
    from . import evaluate, store

    own = conn is None
    conn = conn or sf.connect(role=sf.names().role_eval)
    try:
        rc = load_run(conn, run_id)
        gold_root = GOLD_ROOT / rc.corpus / rc.revision
        run_dir = RESULTS_ROOT / rc.corpus / rc.revision / "runs" / run_id
        meta = {p: {"style": p.partition("--")[2] or None} for p in rc.pdf_ids}
        with tempfile.TemporaryDirectory(prefix="jpcalc_eval_") as tmp:
            res = evaluate.evaluate_run(rc.corpus, gold_root, run_dir, rc.pdf_ids, Path(tmp), meta)
        res.update(run_id=run_id, dataset_revision=rc.revision)
        n = store.write_db(
            conn, res, eval_run_id=eval_run_id, image_tag=os.environ.get("JPCALC_IMAGE_TAG")
        )
        return {
            "run_id": run_id,
            "eval_run_id": eval_run_id,
            "n_rule_rows": n,
            "n_pdfs": res["n_pdfs"],
        }
    finally:
        if own:
            conn.close()

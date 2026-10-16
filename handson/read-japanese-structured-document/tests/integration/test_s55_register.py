"""S55（SQL の登録）と load/rows.py（Python の仕様）の一致。検証用接続が要る。

  SNOWFLAKE_CONNECTION_NAME=<接続名> JPDOCREAD_IT_RUN_ID=<S55 済みの run_id> uv run pytest -m integration

S55 を流した run の出力 JSON をステージから取り、表ごとに全行・全列を Python の結果と比べる。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from jpdocread.load import rows as spec

pytestmark = pytest.mark.integration


def _norm(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return json.loads(v)  # VARIANT・ARRAY はコネクタが JSON 文字列で返す
        except ValueError:
            return v
    return v


@pytest.fixture(scope="module")
def registered(tmp_path_factory):
    run_id = os.environ.get("JPDOCREAD_IT_RUN_ID")
    if not run_id:
        pytest.skip("JPDOCREAD_IT_RUN_ID（S55 済みの run）が無い")
    from jpdocread.common import sf

    n = sf.names()
    conn = sf.connect(role=n.role_predict)
    out_dir = tmp_path_factory.mktemp("s55")
    docs = sf.query(
        conn,
        f"SELECT corpus, doc_id, output_uri FROM {n.fq('schema_output', 'DOCUMENTS')} WHERE run_id = %s",
        (run_id,),
    )
    assert docs, f"DOCUMENTS に run が無い: {run_id}"
    outputs = {}
    for d in docs:
        sf.query(conn, f"GET '{d['output_uri']}' 'file://{out_dir}/'")
        outputs[d["doc_id"]] = (d["corpus"], d["output_uri"],
                                json.loads((Path(out_dir) / f"{d['doc_id']}.json").read_text()))  # fmt: skip
    yield conn, n, run_id, outputs
    conn.close()


@pytest.mark.parametrize("table", spec.TABLES)
def test_sql_rows_equal_python_rows(registered, table):
    from jpdocread.common import sf

    conn, n, run_id, outputs = registered
    cols = spec.columns(table)
    order = "doc_id" + (", seq" if table != "DOCUMENTS" else "")
    got = sf.query(
        conn,
        f"SELECT {', '.join(cols)} FROM {n.fq('schema_output', table)} WHERE run_id = %s ORDER BY {order}",
        (run_id,),
    )
    want = []
    for doc_id in sorted(outputs):
        corpus, uri, out = outputs[doc_id]
        want += spec.to_rows(out, run_id=run_id, corpus=corpus, output_uri=uri)[table]
    got = [{c: _norm(r[c]) for c in cols} for r in got]
    want = [{c: r[c] for c in cols} for r in want]
    assert len(got) == len(want)
    for g, w in zip(got, want, strict=True):
        assert g == w

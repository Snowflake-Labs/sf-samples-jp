"""Snowflake への接続と、ステップの台帳への記録。

接続は 2 通り：
  SPCS ジョブの中  /snowflake/session/token の OAuth（サービスのオーナーロールで動く。資格情報を持ち込まない）
  ローカル         接続名（環境変数 SNOWFLAKE_CONNECTION_NAME → configs/deploy.local.env の順に解決）と予測ロール。
                   接続した後に USE SECONDARY ROLES NONE を実行する（アカウントの既定の副ロールに頼らない）

DB・スキーマ・ロール・ウェアハウスの名前は configs/deploy.env の接頭辞から組み立てる（common/names.py）。
接続名・アカウント識別子・ユーザー名をコードに書かない。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .local_settings import resolve_connection_name
from .names import Names, load_names

TOKEN_PATH = Path("/snowflake/session/token")
_IDENT = re.compile(r"^[A-Z][A-Z0-9_]{0,254}$")


def names() -> Names:
    return load_names()


def fq(schema_attr: str, obj: str, n: Names | None = None) -> str:
    """予測側の DB の <スキーマ>.<オブジェクト> の完全修飾名。schema_attr は Names の属性名（schema_work など）。"""
    n = n or names()
    return f"{n.db}.{getattr(n, schema_attr)}.{obj}"


def in_spcs() -> bool:
    return TOKEN_PATH.exists()


def connect(role: str | None = None, *, use_warehouse: bool = True):
    """use_warehouse=False は setup・teardown 用（ウェアハウスがまだ無い・もう無い状態で接続する）。"""
    import snowflake.connector

    n = names()
    if in_spcs():
        return snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"],
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            token=TOKEN_PATH.read_text().strip(),
            authenticator="oauth",
            warehouse=n.warehouse,
            client_session_keep_alive=True,
        )
    # ロールはログインの後に USE ROLE で切り替える。OAuth の接続はトークンがログイン時のロールに結び付くので、
    # 接続の引数で別のロールを指定すると認可のやり直しになる
    conn = snowflake.connector.connect(connection_name=resolve_connection_name())
    target = role or n.role_predict
    if not _IDENT.match(target):
        raise ValueError(f"ロール名に使えない文字がある: {target!r}")
    query(conn, f"USE ROLE {target}")
    query(conn, "USE SECONDARY ROLES NONE")
    if use_warehouse:
        query(conn, f"USE WAREHOUSE {n.warehouse}")
    return conn


def query(conn, sql: str, params=None) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        cur.close()


def record(
    conn,
    run_id: str,
    step: str,
    doc_id: str,
    status: str,
    *,
    n_errors: int = 0,
    error_text: str | None = None,
    output_uri: str | None = None,
    detail: dict | None = None,
) -> None:
    """STEP_RUNS に (run_id, step, doc_id) の状態を書く（RUNNING で始め、SUCCEEDED / FAILED で終える）。"""
    query(
        conn,
        f"""
        MERGE INTO {fq("schema_ops", "STEP_RUNS")} t
        USING (SELECT %(run_id)s AS run_id, %(step)s AS step, %(doc_id)s AS doc_id) s
          ON t.run_id = s.run_id AND t.step = s.step AND t.doc_id = s.doc_id
        WHEN MATCHED THEN UPDATE SET status = %(status)s,
          started_at = IFF(%(status)s = 'RUNNING', CURRENT_TIMESTAMP(), t.started_at),
          ended_at = IFF(%(status)s = 'RUNNING', NULL, CURRENT_TIMESTAMP()),
          attempt = t.attempt + IFF(%(status)s = 'RUNNING', 1, 0), image_tag = COALESCE(%(tag)s, t.image_tag),
          n_errors = %(n_errors)s, error_text = %(error_text)s, output_uri = COALESCE(%(output_uri)s, t.output_uri),
          detail = TRY_PARSE_JSON(%(detail)s)
        WHEN NOT MATCHED THEN INSERT (run_id, step, doc_id, status, started_at, ended_at, attempt, image_tag,
          n_errors, error_text, output_uri, detail)
          VALUES (%(run_id)s, %(step)s, %(doc_id)s, %(status)s, CURRENT_TIMESTAMP(),
                  IFF(%(status)s = 'RUNNING', NULL, CURRENT_TIMESTAMP()), 1, %(tag)s, %(n_errors)s, %(error_text)s,
                  %(output_uri)s, TRY_PARSE_JSON(%(detail)s))""",
        {
            "run_id": run_id,
            "step": step,
            "doc_id": doc_id,
            "status": status,
            "tag": os.environ.get("JPCALC_IMAGE_TAG"),
            "n_errors": n_errors,
            "error_text": (error_text or None) and error_text[:8000],
            "output_uri": output_uri,
            "detail": json.dumps(detail, ensure_ascii=False, default=str)
            if detail is not None
            else None,
        },
    )

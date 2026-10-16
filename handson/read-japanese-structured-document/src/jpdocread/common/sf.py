"""Snowflake 接続とステップ台帳（予測側・採点側の共通基盤）。

接続は 2 通り：
  SPCS ジョブ内  /snowflake/session/token の OAuth と SNOWFLAKE_HOST・SNOWFLAKE_ACCOUNT（SPCS が注入する）を使う。
                 サービスのオーナーロールで動き、資格情報をイメージ・仕様・ログに持ち込まない
  ローカル       接続名（common.local_settings：環境変数 → configs/deploy.local.env。リポジトリに書かない）

台帳 <DB>.<OPS>.STEP_RUNS は (run_id, step, doc_id) ごとに最新の状態を 1 行で持つ。
再実行の判定は「その行が SUCCEEDED か」だけで行う。
"""

from __future__ import annotations

import json
import os
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .names import Names, load_names

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection

TOKEN_PATH = Path("/snowflake/session/token")
# ジョブ仕様が渡す（ローカルでは未設定。未設定なら deploy.env の名前を使う）
WAREHOUSE_ENV = "JPDOCREAD_WAREHOUSE"
ROLE_ENV = "JPDOCREAD_ROLE"


def in_spcs() -> bool:
    return TOKEN_PATH.exists()


def names() -> Names:
    return load_names()


def ops(n: Names | None = None) -> str:
    return (n or names()).fq("schema_ops")


def connect(role: str | None = None) -> SnowflakeConnection:
    """接続を返す。role を渡せばそのロールで（SECONDARY ROLES は NONE にする）。"""
    import snowflake.connector

    n = names()
    wh = os.environ.get(WAREHOUSE_ENV) or n.warehouse
    if in_spcs():
        conn = snowflake.connector.connect(
            host=os.environ["SNOWFLAKE_HOST"],
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            token=TOKEN_PATH.read_text().strip(),
            authenticator="oauth",
            warehouse=wh,
            client_session_keep_alive=True,
        )
    else:
        conn = _connect_local(wh, role or os.environ.get(ROLE_ENV))
    if role:
        query(conn, f"USE ROLE {_ident(role)}")
    query(conn, "USE SECONDARY ROLES NONE")
    return conn


def _ident(name: str) -> str:
    """埋め込む識別子（ロール名など）の形を限る（SQL インジェクション対策）。"""
    if not name.replace("_", "").isalnum():
        raise ValueError(
            f"識別子の形が不正: {name!r}（英数字と _ だけ。configs/deploy.env の名前を確かめる）"
        )
    return name


def _connect_local(warehouse: str, role: str | None) -> SnowflakeConnection:
    import snowflake.connector

    from .local_settings import resolve_connection_name

    name = resolve_connection_name()
    kw: dict = {"warehouse": warehouse}
    if role:
        kw["role"] = role
    # snow CLI の connections.toml は鍵ファイルを `private_key_path` で持つが、Python コネクタは
    # `private_key_file` を読む。設定ファイルは書き換えず、ここで読み替えて渡す（値はログに出さない）
    cfg = _connection_entry(name)
    if cfg.get("private_key_path") and not cfg.get("private_key_file"):
        allowed = ("account", "user", "authenticator", "role", "host", "private_key_file_pwd")
        kw = {**{k: v for k, v in cfg.items() if k in allowed}, **kw}
        kw["private_key_file"] = cfg["private_key_path"]
        return snowflake.connector.connect(**kw)
    return snowflake.connector.connect(connection_name=name, **kw)


def _connection_entry(name: str) -> dict:
    import tomllib

    home = Path(os.environ.get("SNOWFLAKE_HOME") or Path.home() / ".snowflake")
    for p in (home / "connections.toml", home / "config.toml"):
        if not p.exists():
            continue
        d = tomllib.loads(p.read_text(encoding="utf-8"))
        entry = d.get(name) or (d.get("connections") or {}).get(name)
        if entry:
            return dict(entry)
    return {}


def query(conn: SnowflakeConnection, sql: str, params: tuple | dict | None = None) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if cur.description is None:
            return []
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    finally:
        cur.close()


def as_list(value: str | list | None) -> list:
    """VARIANT の配列（文字列で返ることがある）を list にする。"""
    if value is None:
        return []
    return json.loads(value) if isinstance(value, str) else list(value)


def done_docs(conn: SnowflakeConnection, run_id: str, step: str) -> set[str]:
    rows = query(
        conn,
        f"SELECT doc_id FROM {ops()}.STEP_RUNS WHERE run_id = %s AND step = %s AND status = 'SUCCEEDED'",
        (run_id, step),
    )
    return {r["doc_id"] for r in rows}


def record(
    conn: SnowflakeConnection,
    run_id: str,
    step: str,
    doc_id: str,
    status: str,
    *,
    n_errors: int = 0,
    error_text: str | None = None,
    output_uri: str | None = None,
    detail: dict | None = None,
    image_tag: str | None = None,
) -> None:
    """(run_id, step, doc_id) の行を最新状態に更新する（無ければ作る）。"""
    query(
        conn,
        f"""
        MERGE INTO {ops()}.STEP_RUNS t
        USING (SELECT %(run_id)s AS run_id, %(step)s AS step, %(doc_id)s AS doc_id) s
          ON t.run_id = s.run_id AND t.step = s.step AND t.doc_id = s.doc_id
        WHEN MATCHED THEN UPDATE SET
          status = %(status)s,
          started_at = IFF(%(status)s = 'RUNNING', CURRENT_TIMESTAMP(), t.started_at),
          ended_at = IFF(%(status)s = 'RUNNING', NULL, CURRENT_TIMESTAMP()),
          attempt = t.attempt + IFF(%(status)s = 'RUNNING', 1, 0),
          image_tag = COALESCE(%(image_tag)s, t.image_tag),
          n_errors = %(n_errors)s, error_text = %(error_text)s,
          output_uri = COALESCE(%(output_uri)s, t.output_uri),
          detail = TRY_PARSE_JSON(%(detail)s)
        WHEN NOT MATCHED THEN INSERT
          (run_id, step, doc_id, status, started_at, ended_at, attempt, image_tag,
           n_errors, error_text, output_uri, detail)
          VALUES (%(run_id)s, %(step)s, %(doc_id)s, %(status)s, CURRENT_TIMESTAMP(),
                  IFF(%(status)s = 'RUNNING', NULL, CURRENT_TIMESTAMP()), 1, %(image_tag)s,
                  %(n_errors)s, %(error_text)s, %(output_uri)s, TRY_PARSE_JSON(%(detail)s))
        """,
        {
            "run_id": run_id,
            "step": step,
            "doc_id": doc_id,
            "status": status,
            "image_tag": image_tag or os.environ.get("JPDOCREAD_IMAGE_TAG"),
            "n_errors": n_errors,
            "error_text": (error_text or None) and error_text[:8000],
            "output_uri": output_uri,
            "detail": json.dumps(detail, ensure_ascii=False) if detail is not None else None,
        },
    )


@contextmanager
def step_doc(
    conn: SnowflakeConnection, run_id: str, step: str, doc_id: str
) -> Iterator[dict[str, Any]]:
    """1 文書ぶんの処理を RUNNING → SUCCEEDED / FAILED で囲む。例外は記録してから再送出する。"""
    record(conn, run_id, step, doc_id, "RUNNING")
    box: dict = {}
    try:
        yield box
    except Exception as e:  # noqa: BLE001 — 記録してから再送出する（黙って捨てない）
        record(
            conn,
            run_id,
            step,
            doc_id,
            "FAILED",
            n_errors=1,
            error_text=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-3000:]}",
        )
        raise
    record(
        conn,
        run_id,
        step,
        doc_id,
        "SUCCEEDED",
        n_errors=int(box.get("n_errors", 0)),
        output_uri=box.get("output_uri"),
        detail=box.get("detail"),
    )

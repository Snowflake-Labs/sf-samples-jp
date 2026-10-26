"""パターン 05 / 06 の run_patterns.py が使う共通ヘルパー。

DATA_AGENT_RUN でエージェントを 1 回呼び、応答を要約する。results/ に保存する JSON からは、
思考ブロック（署名を含む）・リクエスト ID・クエリ ID など環境を特定できる値を取り除く。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import subprocess
import time
from typing import Any

DROP_KEYS = {"signature", "request_id", "query_id", "sql_exec_id", "thinking", "encrypted",
             "thread_id", "message_id", "assistant_message_id", "metadata"}


def parse_args(description: str, default_db_env: str, default_db: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("-n", "--runs", type=int, default=int(os.environ.get("MAP_RUNS", "3")),
                    help="パターンごとの実行回数（既定 3、MAP_RUNS で変更可）")
    ap.add_argument("-c", "--connection", default=os.environ.get("MAP_CONNECTION"),
                    help="snow CLI の接続名（または MAP_CONNECTION）")
    args = ap.parse_args()
    if not args.connection:
        ap.error("接続が指定されていません: -c <接続名> または MAP_CONNECTION を設定してください")
    args.db = os.environ.get(default_db_env, default_db)
    args.wh = os.environ.get("MAP_WAREHOUSE", "MULTI_AGENT_PATTERNS_WH")
    for value in (args.db, args.wh):
        if not value.replace("_", "").isalnum():
            ap.error(f"不正な識別子: {value}")
    return args


def run_agent(args: argparse.Namespace, agent: str, prompt: str) -> tuple[dict[str, Any], int, float]:
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]})
    sql = f"USE WAREHOUSE {args.wh}; SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('{args.db}.LAB.{agent}', $${body}$$) AS R"
    started = time.time()
    p = subprocess.run(["snow", "sql", "-c", args.connection, "--format", "json", "-q", sql],
                       capture_output=True, text=True, timeout=900)
    secs = round(time.time() - started, 1)
    if p.returncode:
        return {"error": p.stderr.strip()[-800:]}, 0, secs
    rows = json.loads(p.stdout)
    rows = rows[-1] if rows and isinstance(rows[0], list) else rows
    raw = rows[0]["R"]
    text = raw if isinstance(raw, str) else json.dumps(raw)
    return json.loads(text), len(text), secs


def sanitize(obj: Any) -> Any:
    """保存前に、環境を特定できる値と思考ブロックを取り除く。"""
    if isinstance(obj, dict):
        if obj.get("type") == "thinking":
            return {"type": "thinking", "thinking": "(removed)"}
        return {k: sanitize(v) for k, v in obj.items() if k not in DROP_KEYS}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    if isinstance(obj, str) and obj.lstrip()[:1] in "{[":
        # MCP のツール結果は「JSON 文字列」や「NDJSON（1 行 1 JSON）」で入れ子になる
        try:
            return json.dumps(sanitize(json.loads(obj)), ensure_ascii=False)
        except json.JSONDecodeError:
            try:
                return "\n".join(json.dumps(sanitize(json.loads(line)), ensure_ascii=False)
                                 for line in obj.splitlines() if line.strip())
            except json.JSONDecodeError:
                return "(removed: unparseable nested payload)"
    return obj


def summarize(resp: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    text, tools, results = "", [], []
    for c in resp.get("content") or []:
        if c.get("type") == "text":
            text += c.get("text", "")
        elif c.get("type") == "tool_use":
            u = c.get("tool_use", {})
            tools.append(f"{u.get('type', '')}:{u.get('name', '')}")
        elif c.get("type") == "tool_result":
            r = c.get("tool_result", {})
            results.append(f"{r.get('name', '')}:{r.get('status', '')}")
    return text, tools, results


def results_dir(script_file: str) -> tuple[pathlib.Path, str]:
    out = pathlib.Path(script_file).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    return out, datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def save(out: pathlib.Path, name: str, obj: Any) -> None:
    (out / name).write_text(json.dumps(sanitize(obj), indent=2, ensure_ascii=False))

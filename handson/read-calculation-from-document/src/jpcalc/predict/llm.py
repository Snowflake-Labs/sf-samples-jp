"""LLM 呼び出しのクライアント（予測側）。

要求を作業スキーマの AI_REQUESTS に書き、運用スキーマの AI_CALL(run_id, batch_id) で一括処理して
作業スキーマの AI_CACHE から読む（名前は configs/deploy.env の接頭辞から組み立てる）。
AI_COMPLETE は SQL の中で集合演算として呼ばれ、キャッシュ・NULL・解析失敗の計数はプロシージャ側で一元化される。
cache_key = sha256(model | max_tokens | prompt_version | prompt)。キーが変わらなければ再課金しない。
キャッシュを使わない実行（start.sh --no-cache）では JPCALC_CACHE_SALT を末尾に足す。空なら同じキー。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass

from ..common import sf

FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class Req:
    stage: str
    doc_id: str
    unit: str
    prompt: str
    max_tokens: int
    prompt_version: str
    model: str
    expect: str = "json"

    @property
    def cache_key(self) -> str:
        parts = [self.model, str(self.max_tokens), self.prompt_version, self.prompt]
        salt = os.environ.get("JPCALC_CACHE_SALT", "")
        if salt:
            parts.append("salt:" + salt)
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass
class Resp:
    req: Req
    raw: str | None
    err: str | None
    parsed: object = None
    cached: bool = False
    attempts: int = 0  # この run で AI_CALL が呼んだ回数（1 回の呼び出しが AI_CACHE の 1 行。前の run のキャッシュに当たれば 0。2 以上なら失敗の呼び直しがあった）

    @property
    def ok(self) -> bool:
        return self.err is None


def strip_fence(s: str) -> str:
    return FENCE.sub("", s.strip())


def parse_json(raw: str):
    s = strip_fence(raw)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", s, re.S)
        if m:
            return json.loads(m.group(0))
        raise


class LLM:
    def __init__(self, conn, run_id: str):
        self.conn = conn
        self.run_id = run_id
        self.stats = {"requests": 0, "called": 0, "cached": 0, "null_output": 0, "parse_error": 0}

    def complete(self, reqs: list[Req]) -> list[Resp]:
        if not reqs:
            return []
        batch = uuid.uuid4().hex[:12]
        rows = [
            (
                self.run_id,
                batch,
                r.cache_key,
                r.stage,
                r.doc_id,
                r.unit,
                r.model,
                r.max_tokens,
                r.prompt_version,
                r.expect,
                r.prompt,
            )
            for r in reqs
        ]
        cur = self.conn.cursor()
        try:
            cur.executemany(
                f"INSERT INTO {sf.fq('schema_work', 'AI_REQUESTS')} (run_id, batch_id, cache_key, stage, doc_id, unit, model, max_tokens,"
                " prompt_version, expect, prompt, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP())",
                rows,
            )
        finally:
            cur.close()
        res = sf.query(
            self.conn, f"CALL {sf.fq('schema_ops', 'AI_CALL')}(%s, %s)", (self.run_id, batch)
        )
        info = json.loads(next(iter(res[0].values()))) if res else {}
        self.stats["requests"] += len(reqs)
        self.stats["called"] += int(info.get("n_called", 0))
        keys = list({r.cache_key for r in reqs})
        got = {}
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            ph = ",".join(["%s"] * len(chunk))
            for row in sf.query(
                self.conn,
                f"""
                SELECT cache_key, raw_out, err, COUNT_IF(run_id = %s) OVER (PARTITION BY cache_key) AS n_run
                FROM {sf.fq("schema_work", "AI_CACHE")} WHERE cache_key IN ({ph})
                QUALIFY ROW_NUMBER() OVER (PARTITION BY cache_key ORDER BY IFF(err IS NULL, 0, 1), called_at DESC) = 1""",
                (self.run_id, *chunk),
            ):
                got[row["cache_key"]] = row
        out = []
        for r in reqs:
            g = got.get(r.cache_key)
            if g is None:
                out.append(Resp(r, None, "missing"))
                continue
            resp = Resp(r, g["raw_out"], g["err"], attempts=int(g.get("n_run") or 0))
            if resp.ok and r.expect == "json":
                try:
                    resp.parsed = parse_json(resp.raw)
                except (json.JSONDecodeError, ValueError):
                    resp.err = "parse_error"
            elif resp.ok:
                resp.parsed = strip_fence(resp.raw)
            if resp.err:
                self.stats[resp.err] = self.stats.get(resp.err, 0) + 1
            out.append(resp)
        self.stats["cached"] = self.stats["requests"] - self.stats["called"]
        return out

"""正解の読み出しと照合（評価側だけ。予測側から呼ばない）。

正解は `jpcalc fetch-gold` が評価用の置き場所（eval_data/<corpus>/<revision>/）に取得する。取得のときに
固定 revision の各ファイルの照合値（LFS は SHA-256、通常のファイルは git の blob ID）を `gold_ids.json` に
記録し、読む前にここで再計算して突き合わせる。一致しなければ GoldMismatch で止める。照合値の無い
ファイル（ローカルの写しから取った場合など）は「未照合」として数を返し、照合済みとはみなさない。

2 つのコーパスで正解の置き場所が違う：
  保険約款  documents/<doc>/calc/{tasks.jsonl, answer_key.json, cases.jsonl, programs/, tests/} と policy.json
  契約書    answers/<cid>/{answer_key.json, cases.jsonl, programs/, tests/} と inputs/<cid>/{tasks.jsonl, contract.json}
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

IDS_FILE = "gold_ids.json"

# 文書 ID を差し込むパスのひな型（評価用の置き場所からの相対パス）
LAYOUT: dict[str, dict[str, str]] = {
    "yakkan": {
        "calc": "documents/{d}/calc",
        "tasks": "documents/{d}/calc/tasks.jsonl",
        "text": "documents/{d}/policy.json",
        "root": "documents/{d}",
    },
    "contract": {
        "calc": "answers/{d}",
        "tasks": "inputs/{d}/tasks.jsonl",
        "text": "inputs/{d}/contract.json",
        "root": "answers/{d}",
        "inputs": "inputs/{d}",
    },
}


class GoldMismatch(RuntimeError):
    """正解のファイルが無い、または照合値と一致しない。"""


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(
        b"blob %d\0" % len(data) + data
    ).hexdigest()  # git の blob ID の定義（安全目的のハッシュではない）


def file_matches(data: bytes, want: dict[str, str]) -> bool:
    if "sha256" in want:
        return hashlib.sha256(data).hexdigest() == want["sha256"]
    if "git_sha1" in want:
        return git_blob_sha1(data) == want["git_sha1"]
    return False


def load_ids(root: Path) -> dict[str, dict[str, str]]:
    p = root / IDS_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_ids(root: Path, ids: dict[str, dict[str, str]]) -> Path:
    """取得した正解の照合値を追記する（既存の記録と食い違えば止める）。"""
    cur = load_ids(root)
    for k, v in ids.items():
        if k in cur and cur[k] != v:
            raise GoldMismatch(f"照合値の記録が食い違う: {k}")
    cur.update(ids)
    p = root / IDS_FILE
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return p


def doc_of(pdf_id: str) -> str:
    """PDF の ID（<doc>--<style>）から文書の ID（正解は文書単位）。"""
    return pdf_id.partition("--")[0]


@dataclass
class Gold:
    """1 文書の正解。root は評価用の置き場所（eval_data/<corpus>/<revision>）。"""

    corpus: str
    root: Path
    doc_id: str

    def __post_init__(self) -> None:
        if self.corpus not in LAYOUT:
            raise ValueError(f"未知のコーパス: {self.corpus}")
        self.doc_id = doc_of(self.doc_id)

    def rel(self, key: str) -> str:
        return LAYOUT[self.corpus][key].format(d=self.doc_id)

    def path(self, key: str) -> Path:
        return self.root / self.rel(key)

    # ---- 照合

    def files(self) -> list[Path]:
        """採点が読むファイル（カード・根拠の本文・answer_key・cases・正解プログラム・テスト・manifest）。"""
        calc = self.path("calc")
        fs = [self.path("tasks"), self.path("text")]
        fs += [calc / n for n in ("answer_key.json", "cases.jsonl", "manifest.json")]
        fs += sorted((calc / "programs").glob("*.py")) + sorted((calc / "tests").glob("*.py"))
        return fs

    def verify(self) -> dict:
        """照合する。戻り値：{verified, unverified: [パス]}。不一致・欠落は GoldMismatch。"""
        ids = load_ids(self.root)
        verified, unverified = 0, []
        fs = self.files()
        if not any(f.parent.name == "programs" for f in fs) or not any(
            f.parent.name == "tests" for f in fs
        ):
            raise GoldMismatch(f"{self.doc_id}: 正解プログラムかテストが無い")
        for f in fs:
            rel = f.relative_to(self.root).as_posix()
            if not f.is_file():
                raise GoldMismatch(f"{self.doc_id}: 正解のファイルが無い {rel}")
            want = ids.get(rel)
            if want is None:
                unverified.append(rel)
                continue
            if not file_matches(f.read_bytes(), want):
                raise GoldMismatch(f"{self.doc_id}: 照合値が一致しない {rel}")
            verified += 1
        return {"verified": verified, "unverified": unverified}

    # ---- 読み出し

    def _jsonl(self, p: Path) -> list[dict]:
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def task_cards(self) -> list[dict]:
        """正解のタスクカード。予測側には渡さず、対応付け M だけが読む。"""
        return self._jsonl(self.path("tasks"))

    def answer_key(self) -> list[dict]:
        return json.loads((self.path("calc") / "answer_key.json").read_text(encoding="utf-8"))

    def cases(self) -> list[dict]:
        return self._jsonl(self.path("calc") / "cases.jsonl")

    def manifest(self) -> dict:
        return json.loads((self.path("calc") / "manifest.json").read_text(encoding="utf-8"))

    def text_json(self) -> dict:
        """根拠の本文の JSON（保険約款 policy.json・契約書 contract.json）。"""
        return json.loads(self.path("text").read_text(encoding="utf-8"))

    def reference_program(self) -> Path:
        ps = sorted((self.path("calc") / "programs").glob("calc_*.py"))
        if not ps:
            raise GoldMismatch(f"{self.doc_id}: 正解プログラムが無い")
        return ps[0]

    def tests_dir(self) -> Path:
        return self.path("calc") / "tests"

    def cases_file(self) -> Path:
        return self.path("calc") / "cases.jsonl"

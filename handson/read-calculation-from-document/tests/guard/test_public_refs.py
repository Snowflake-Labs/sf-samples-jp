"""公開するファイルが、公開しない開発用の文書を参照していないこと。

開発用の文書（作業規約・作業台帳・docs/ 以下の設計と判断の記録）は git 管理外で公開しない。
公開するファイルにその節番号・判断番号・タスク番号が残ると、読者が辿れない参照になる。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fixtures.repo_files import publishable_files

from jpcalc.common.paths import HOME

PRIVATE_REFS = {
    "docs_dir": re.compile(r"(?<![A-Za-z0-9_./-])docs/"),
    "decision_id": re.compile(r"\bD-\d{3}\b"),
    "task_id": re.compile(r"\bT\d{1,2}\.(?:[A-Z]\.)?\d{1,2}\b"),
    "dev_doc_section": re.compile(
        r"(?:AGENTS|TASK|DESIGN|DECISIONS|IMPROVEMENT_PROPOSAL)(?:\.md)?\s*§"
    ),
}
# このテスト自身と、非公開のファイルが公開対象に入っていないことを確かめるテストは検査の対象外
EXEMPT = {Path(__file__).resolve(), (HOME / "tests/guard/test_no_secrets.py").resolve()}
FILES = [p for p in publishable_files() if p.resolve() not in EXEMPT and p.name != ".gitignore"]


def find_private_refs(text: str) -> list[str]:
    return [name for name, rx in PRIVATE_REFS.items() if rx.search(text)]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(HOME)))
def test_no_refs_to_private_docs(path):
    assert find_private_refs(path.read_text(encoding="utf-8", errors="ignore")) == []


class TestDetector:
    @pytest.mark.parametrize(
        "text",
        [
            "docs/DESIGN.md §4",
            "（D-012）",
            "TASK.md T2.7",
            "AGENTS.md §7.4",
            "（T1.5）",
            "（T10.B.3）",
            "IMPROVEMENT_PROPOSAL §12.4",
        ],
    )
    def test_detects(self, text):
        assert find_private_refs(text)

    @pytest.mark.parametrize(
        "text", ["https://docs.astral.sh/uv/", "親リポジトリの AGENTS.md", "Python 3.11", "v1.0"]
    )
    def test_allows(self, text):
        assert find_private_refs(text) == []

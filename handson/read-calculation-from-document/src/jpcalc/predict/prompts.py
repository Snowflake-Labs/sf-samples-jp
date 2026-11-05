"""プロンプトの雛形（configs/prompts/<版>.txt）に差し込みを入れる共通の口。

差し込みは与えた順に置き換える（差し込んだ値が別の差し込み名を含むときに結果が順番で変わるため）。
雛形に無い差し込み名は何もしない（古い版の雛形にも同じ呼び方で使えるように）。"""

from __future__ import annotations

from ..common.paths import CONFIGS


def template(version: str) -> str:
    return (CONFIGS / "prompts" / f"{version}.txt").read_text(encoding="utf-8")


def fill(version: str, slots: list[tuple[str, str]]) -> str:
    t = template(version)
    for name, value in slots:
        t = t.replace(f"<<{name}>>", value)
    return t

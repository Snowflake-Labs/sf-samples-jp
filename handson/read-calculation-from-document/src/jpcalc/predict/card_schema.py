"""合成カードの schema（configs/schema/card.schema.json）による検査。

カードは予測と採点の間の契約なので、予測の出力を書く前にこの schema で確かめる。
単位の語彙は schema に書かず、K の決定的な検査（configs/conventions.yaml の units）で照合する。
"""

from __future__ import annotations

import json
from functools import lru_cache

import jsonschema

from ..common.paths import CONFIGS


@lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads((CONFIGS / "schema" / "card.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def check_card(card: dict) -> list[str]:
    """schema に合わない点の一覧（空なら合格）。"""
    fn = card.get("function", "?") if isinstance(card, dict) else "?"
    return [
        f"{fn}: card schema: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
        for e in sorted(
            _validator().iter_errors(card), key=lambda e: list(map(str, e.absolute_path))
        )
    ]

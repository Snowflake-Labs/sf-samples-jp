"""図の設定（pipeline.yaml の figure）と、移植した read/figures.py の定数が一致すること。

両者が違えば、setup の前にこのテストで止める。
"""

from __future__ import annotations

from jpdocread.config import load_pipeline_config
from jpdocread.read import figures


def test_figure_model_and_prompt_version_match_ported_constants():
    f = load_pipeline_config().figure
    assert f.model == figures.MODEL_DEFAULT
    assert f.prompt_version == figures.PROMPT_VERSION


def test_max_tokens_constants_match():
    f = load_pipeline_config().figure
    assert (f.max_tokens_min, f.max_tokens_per_node) == (
        figures.MIN_MAX_TOKENS,
        figures.TOKENS_PER_ELEM,
    )


def test_prompt_rules_have_no_bare_brace():
    """PROMPT() の本文に素の { があると全行が黙って NULL になる（移植元 F7）。"""
    import re

    assert re.search(r"\{(?!\d\})", figures.RULES) is None

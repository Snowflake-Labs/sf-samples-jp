"""テスト用の設定（架空のコーパス）。"""

from __future__ import annotations

from jpdocread.config import CorpusConfig, PipelineConfig


def make_pipeline_cfg(**overrides) -> PipelineConfig:
    data = {
        "figure": {
            "model": "m",
            "prompt_version": "v1",
            "max_tokens_min": 4096,
            "max_tokens_per_node": 180,
        },
        "cost": {"parse_layout_credits_per_page": 0.01, "figure_credits_per_call": 0.1},
        "defaults": {"slice": "pilot", "confirm_slices": ["all"]},
    }
    data.update(overrides)
    return PipelineConfig.model_validate(data)


def corpus_dict(**overrides) -> dict:
    data = {
        "name": "testcorpus",
        "title": "テスト用コーパス",
        "source": {"kind": "local", "local": {"path": "/unused"}},
        "structure_builder": "auto",
        # 供出元は aaa の 2 版面。同じ content なので両方とも評価から外す
        "figure_shots": ["aaa-0001--style-a", "aaa-0001--style-b"],
        "eval_excluded": ["aaa-0001--style-a", "aaa-0001--style-b"],
        "slices": {
            "pilot": ["bbb-0001--style-a"],
            "two": ["aaa-0001--style-a", "bbb-0001--style-a"],
        },
        "cost": {"figure_regions_per_gold_figure": 2.0},
    }
    data.update(overrides)
    return data


def make_corpus_cfg(**overrides) -> CorpusConfig:
    return CorpusConfig.model_validate(corpus_dict(**overrides))

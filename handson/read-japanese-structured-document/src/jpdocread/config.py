"""設定の読み込みと検証。

- configs/pipeline.yaml         … 共通（図・見込みクレジットの単価・既定スライス）
- configs/corpora/<name>.yaml   … コーパス固有（データソース・組み立て器・供出元・評価除外・スライス）

未知のキー・型違い・矛盾（供出元が評価除外に無い、pilot に評価除外の文書がある等）はここで止める。
`${VAR}` は環境変数 → configs/deploy.local.env の順で展開し、未定義なら空のまま残さずエラーにする。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .common.local_settings import lookup_local
from .common.paths import CORPORA, DEPLOY_LOCAL_ENV, PIPELINE_YAML

ALL_SLICE = "all"
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(ValueError):
    """設定ファイルが不正・未記入。"""


_ModelT = TypeVar("_ModelT", bound=BaseModel)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- pipeline.yaml -----------------------------------------------------------


class FigureConfig(_Strict):
    model: str
    prompt_version: str
    max_tokens_min: int = Field(gt=0)
    max_tokens_per_node: int = Field(gt=0)
    retry_parse_error: int = Field(default=1, ge=0, le=3)


class CostConfig(_Strict):
    parse_layout_credits_per_page: float = Field(ge=0)
    figure_credits_per_call: float = Field(ge=0)


class DefaultsConfig(_Strict):
    slice: str
    confirm_slices: list[str] = Field(default_factory=list)


class PipelineConfig(_Strict):
    figure: FigureConfig
    cost: CostConfig
    defaults: DefaultsConfig


# --- corpora/<name>.yaml -----------------------------------------------------


class LocalSourceConfig(_Strict):
    path: str | None = None


class HuggingFaceSourceConfig(_Strict):
    repo_id: str | None = None
    revision: str | None = None


class SourceConfig(_Strict):
    kind: Literal["local", "huggingface"]
    local: LocalSourceConfig = LocalSourceConfig()
    huggingface: HuggingFaceSourceConfig = HuggingFaceSourceConfig()


class FeaturesConfig(_Strict):
    parties: bool = False
    defined_terms: bool = False


class TablesConfig(_Strict):
    # ページ・段をまたぐ表を 1 つにつなぐか（read/stitch.py）。False なら従来どおりページごとの表を出す
    stitch: bool = False


class CorpusCostConfig(_Strict):
    figure_regions_per_gold_figure: float = Field(ge=0)


class CorpusConfig(_Strict):
    name: str
    title: str
    source: SourceConfig
    structure_builder: Literal["auto", "yakkan", "contract"]
    features: FeaturesConfig = FeaturesConfig()
    tables: TablesConfig = TablesConfig()
    figure_shots: list[str]
    eval_excluded: list[str]
    slices: dict[str, list[str]]
    cost: CorpusCostConfig
    # 出力 JSON の provenance.known_limits にそのまま入れる（移植元の実測値と出典。数値をコードに書かない）
    known_limits: dict[str, str | int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_consistency(self) -> CorpusConfig:
        if ALL_SLICE in self.slices:
            raise ValueError(f"スライス {ALL_SLICE!r} は manifest から決まるので書かない")
        donors = set(self.figure_shots)
        excluded = set(self.eval_excluded)
        if not donors <= excluded:
            raise ValueError(f"figure_shots が eval_excluded に無い: {sorted(donors - excluded)}")
        for name, docs in self.slices.items():
            if len(docs) != len(set(docs)):
                raise ValueError(f"スライス {name!r} に重複がある")
        pilot = set(self.slices.get("pilot", []))
        if pilot & excluded:
            raise ValueError(f"pilot に評価除外の文書がある: {sorted(pilot & excluded)}")
        return self


# --- 読み込み ----------------------------------------------------------------


def expand_vars(
    value: str,
    *,
    env: Mapping[str, str] | None = None,
    local_env_path: Path = DEPLOY_LOCAL_ENV,
) -> str:
    """`${VAR}` を展開する。未定義・未記入（ひな型の `<...>` のまま）ならエラー。"""

    def repl(m: re.Match[str]) -> str:
        found = lookup_local(m.group(1), env=env, local_env_path=local_env_path)
        if found is None:
            raise ConfigError(
                f"{m.group(1)} が未設定（環境変数か {local_env_path.name} に書く。"
                "configs/deploy.env.example を参照）"
            )
        return found

    return _VAR_RE.sub(repl, value)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"設定ファイルが無い: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: YAML の最上位がマッピングでない")
    return data


def _validate(model: type[_ModelT], data: dict, path: Path) -> _ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path}: {e}") from e


def load_pipeline_config(path: Path = PIPELINE_YAML) -> PipelineConfig:
    return _validate(PipelineConfig, _load_yaml(path), path)


def available_corpora(corpora_dir: Path = CORPORA) -> list[str]:
    return sorted(p.stem for p in corpora_dir.glob("*.yaml"))


def load_corpus_config(name: str, corpora_dir: Path = CORPORA) -> CorpusConfig:
    path = corpora_dir / f"{name}.yaml"
    if not path.exists():
        raise ConfigError(
            f"コーパス {name!r} の設定が無い。選べるもの: {available_corpora(corpora_dir)}"
        )
    cfg = _validate(CorpusConfig, _load_yaml(path), path)
    if cfg.name != name:
        raise ConfigError(f"{path}: name={cfg.name!r} がファイル名と一致しない")
    return cfg

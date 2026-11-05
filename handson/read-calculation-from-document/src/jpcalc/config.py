"""設定ファイルを型付きで読む（configs/pipeline.yaml・corpora/*.yaml・conventions.yaml・guard.yaml）。

未知のキーと不正な値はエラーにする（書き間違いを黙って既定値で通さない）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .common.paths import CONVENTIONS_YAML, CORPORA, GUARD_YAML, PIPELINE_YAML

CorpusName = Literal["yakkan", "contract"]
CORPUS_NAMES: tuple[str, ...] = ("yakkan", "contract")
UNITS: tuple[str, ...] = ("JPY", "DAY", "MONTH", "YEAR", "HOUR", "MIN", "COUNT", "GRADE", "INDEX")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_MODEL = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


class ConfigError(ValueError):
    """設定ファイルが無い・書式が不正。"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- pipeline.yaml ----------------------------------------------------------------------------


class MaxTokens(_Strict):
    k_cards: int = Field(gt=0)
    d_spec: int = Field(gt=0)
    t_examples: int = Field(gt=0)
    t_crosscheck: int = Field(gt=0)
    r_repair: int = Field(gt=0)


class LlmCfg(_Strict):
    model: str
    temperature: float = Field(ge=0, le=1)
    max_tokens: MaxTokens

    @field_validator("model")
    @classmethod
    def _model_name(cls, v: str) -> str:
        # モデル名は SQL へ渡すので、英小文字・数字・. - だけを許す
        if not _MODEL.match(v):
            raise ValueError(f"モデル名に使えない文字がある: {v!r}")
        return v


class KCfg(_Strict):
    prompt: str
    rescan: bool
    rescan_prompt: str
    repair: bool
    repair_prompt: str


class RepairCfg(_Strict):
    max_iter: int = Field(ge=0, le=10)


class SelftestCfg(_Strict):
    boundary_delta: tuple[int, ...]
    random_cases: int = Field(ge=0)
    crosscheck_points: int = Field(ge=0)
    crosscheck_mode: Literal["report"]


class SandboxCfg(_Strict):
    timeout_sec: int = Field(gt=0)
    per_call_timeout_sec: int = Field(gt=0)


class SliceCfg(_Strict):
    pilot: tuple[str, ...] = ()
    shots: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _disjoint(self) -> SliceCfg:
        both = set(self.pilot) & set(self.shots)
        if both:
            raise ValueError(f"pilot と shots が重なっている: {sorted(both)}")
        return self


class RunCfg(_Strict):
    # 予測ジョブは対象を chunk_pdfs 件ずつ処理し、まとまりごとに段 P を台帳に記録する
    # （Task の時間制限で切れても、--resume で終わったまとまりを飛ばす）
    chunk_pdfs: int = Field(default=4, gt=0)


class PipelineCfg(_Strict):
    llm: LlmCfg
    k: KCfg
    repair: RepairCfg
    selftest: SelftestCfg
    sandbox: SandboxCfg
    run: RunCfg = RunCfg()
    slices: dict[CorpusName, SliceCfg]

    @model_validator(mode="after")
    def _both_corpora(self) -> PipelineCfg:
        missing = set(CORPUS_NAMES) - set(self.slices)
        if missing:
            raise ValueError(f"slices にコーパスが無い: {sorted(missing)}")
        return self


# ---- corpora/*.yaml ---------------------------------------------------------------------------


class HfSource(_Strict):
    repo_id: str
    revision: str

    @field_validator("revision")
    @classmethod
    def _pinned(cls, v: str) -> str:
        # main・タグ・短縮 SHA は不可
        if not _SHA40.match(v):
            raise ValueError(f"revision は 40 桁のコミット SHA にする: {v!r}")
        return v


class LocalSourceCfg(_Strict):
    path: str


class SourceCfg(_Strict):
    kind: Literal["huggingface", "local"]
    huggingface: HfSource
    local: LocalSourceCfg


class LicenseCfg(_Strict):
    dataset: Literal["CC-BY-4.0"]
    attribution: str
    notices: tuple[str, ...]


class IndexColumns(_Strict):
    doc_id: str
    split_group: str
    stratum: str
    styles: str
    pages: str
    pdf_file: str | None = Field(...)  # 列が無いときは null と明示する


class IndexCfg(_Strict):
    file: str
    records: str | None = Field(...)  # JSON Lines（1 行 1 文書）のときは null と明示する
    columns: IndexColumns
    sha256_from: Literal["index_files", "hub_paths_info"]


class PathsCfg(_Strict):
    pdf: str
    pdf_id: str
    gold: tuple[str, ...]
    gold_root: str
    gold_tests: str

    @field_validator("pdf")
    @classmethod
    def _pdf_only(cls, v: str) -> str:
        if not v.endswith(".pdf"):
            raise ValueError(f"予測用のパスは PDF だけ: {v!r}")
        return v


class SplitCfg(_Strict):
    salt: str = Field(min_length=1)
    dev_fraction: float = Field(gt=0, lt=1)


class HarnessCfg(_Strict):
    date_args: Literal["DATE_ARGS", "TYPES"]
    calendar: bool


class CorpusCfg(_Strict):
    name: CorpusName
    title: str
    source: SourceCfg
    license: LicenseCfg
    index: IndexCfg
    paths: PathsCfg
    split: SplitCfg
    harness: HarnessCfg
    # 予測の開始時に当てる読み出し口の値（common/tunables.py の KNOWN の名前だけ）。既定は空＝今の動作のまま。
    # 検証で採用した設定だけを、判定の記録と人の承認を条件に入れる
    tuning: dict[str, float | int | list[str]] = Field(default_factory=dict)

    @field_validator("tuning", mode="before")
    @classmethod
    def _tuning_known(cls, v: dict) -> dict:
        from .common.tunables import validate

        # 型の変換（bool→数・文字列→数・tuple→list）の前の値で検査する
        if not isinstance(v, dict):
            raise ValueError("tuning: は名前 → 値の対応")
        probs = validate(v)
        if probs:
            raise ValueError("tuning: " + "; ".join(probs))
        return v


# ---- conventions.yaml・guard.yaml -------------------------------------------------------------


class Conventions(_Strict):
    call: str
    money: str
    date: str
    bool: str
    unknown: str
    days: str
    list: str
    omitted: str
    calendar: str
    kind: str
    units: tuple[str, ...]

    @field_validator("units")
    @classmethod
    def _units(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(v) != UNITS:
            raise ValueError(f"単位の語彙が規約と違う: {list(v)}（期待：{list(UNITS)}）")
        return v


class GuardCfg(_Strict):
    forbidden_names: tuple[str, ...]
    strict_dir_names: tuple[str, ...]
    boundary_dir_parts: tuple[str, ...]
    predict_allow: dict[CorpusName, tuple[str, ...]]
    forbidden_imports: tuple[str, ...]

    @field_validator("strict_dir_names")
    @classmethod
    def _names(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [p for p in v if not p or "/" in p]
        if bad:
            raise ValueError(f"strict_dir_names は '/' を含まない名前にする: {bad}")
        return v

    @field_validator("boundary_dir_parts")
    @classmethod
    def _dirs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [p for p in v if not p.endswith("/") or p.startswith("/")]
        if bad:
            raise ValueError(f"boundary_dir_parts は 'name/' の形にする: {bad}")
        return v

    @model_validator(mode="after")
    def _both_corpora(self) -> GuardCfg:
        missing = set(CORPUS_NAMES) - set(self.predict_allow)
        if missing:
            raise ValueError(f"predict_allow にコーパスが無い: {sorted(missing)}")
        return self

    @model_validator(mode="after")
    def _allow_is_pdf(self) -> GuardCfg:
        for corpus, pats in self.predict_allow.items():
            for p in pats:
                if not p.endswith(".pdf"):
                    raise ValueError(f"{corpus}: 予測用 allow-list は PDF だけ: {p!r}")
        return self


# ---- 読み込み ---------------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"設定ファイルが無い: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: YAML として読めない: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: 最上位が辞書でない")
    return data


def _validate(model: type[_Strict], path: Path, data: dict):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"{path}: {e}") from e


def load_pipeline_config(path: Path = PIPELINE_YAML) -> PipelineCfg:
    return _validate(PipelineCfg, path, _load_yaml(path))


def load_corpus_config(name: str, corpora_dir: Path = CORPORA) -> CorpusCfg:
    if name not in CORPUS_NAMES:
        raise ConfigError(f"未知のコーパス: {name!r}（{' | '.join(CORPUS_NAMES)}）")
    path = corpora_dir / f"{name}.yaml"
    cfg = _validate(CorpusCfg, path, _load_yaml(path))
    if cfg.name != name:
        raise ConfigError(f"{path}: name が {cfg.name!r}（ファイル名は {name!r}）")
    return cfg


def load_conventions(path: Path = CONVENTIONS_YAML) -> Conventions:
    return _validate(Conventions, path, _load_yaml(path))


def load_guard_config(path: Path = GUARD_YAML) -> GuardCfg:
    return _validate(GuardCfg, path, _load_yaml(path))

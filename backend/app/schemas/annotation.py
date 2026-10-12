from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnnotationKind = Literal["protein", "phospho", "phosprot"]
MetadataAnnotationKind = Literal["protein", "phospho"]
FilterMethod = Literal["at_least_n", "percentage"]
# The matrix an analysis runs on, in ladder order: least processed first.
# One name, one meaning, everywhere -- the UI options, the request schemas and
# `analysis_matrix.select_matrix` all read from this.
DataSource = Literal["data", "filtered", "imputed"]
# What an analysis actually ran on, as reported back. Wider than `DataSource`:
# it can name a matrix nobody can request -- "raw" and "log2" are reached only by
# the imputation diagnostics, which follow the imputation's own input.
ResolvedSource = Literal["data", "filtered", "log2", "raw", "imputed"]
FilterMode = Literal["per_group", "in_at_least_one_group", "overall"]
NormalizationMethod = Literal["none", "median", "quantile", "vsn"]
MetadataSource = Literal["manual", "auto", "uploaded", "shared_phospho"]
PhosprotAggregationMode = Literal[
    "robust_site_median",
    "sum_propagate_na",
    "sum_ignore_na",
    "mean",
]
PhosprotAggregationSource = Literal["non_imputed", "imputed"]


class ConditionAssignment(BaseModel):
    name: str = Field(min_length=1)
    columns: list[str] = Field(default_factory=list)


class SamplePairAssignment(BaseModel):
    condition1Sample: str = Field(min_length=1)
    condition2Sample: str = Field(min_length=1)


class PairingUpdateRequest(BaseModel):
    kind: AnnotationKind
    condition1: str = Field(min_length=1)
    condition2: str = Field(min_length=1)
    pairs: list[SamplePairAssignment] = Field(min_length=2)


class IdentifierTranslationStep(BaseModel):
    sourceColumn: str
    inputDb: str
    outputDb: str
    toolVersion: str
    outputs: dict[str, dict[str, str]]


class AnnotationFilterConfig(BaseModel):
    method: FilterMethod = "at_least_n"
    minPresent: int = Field(default=0, ge=0)
    minPercentage: float = Field(default=70.0, ge=0.0, le=100.0)
    mode: FilterMode = "per_group"
    # Applied to protein/phosphosite log2 matrices before filtering. Always
    # global, never per condition. Phosphoprotein annotations are forced to
    # "none" because their upstream phosphosite matrix was already normalized.
    normalization: NormalizationMethod = "none"


def phosprot_filter_config(config: AnnotationFilterConfig) -> AnnotationFilterConfig:
    """Retain inherited filtering while preventing post-collapse normalization."""
    return config.model_copy(update={"normalization": "none"})


class AnnotationGenerateRequest(BaseModel):
    kind: AnnotationKind
    conditions: list[ConditionAssignment] = Field(default_factory=list)
    isLog2Transformed: bool | None = None
    filter: AnnotationFilterConfig | None = None


class Log2DetectionRequest(BaseModel):
    kind: AnnotationKind
    sampleColumns: list[str] = Field(default_factory=list)


class Log2DetectionResponse(BaseModel):
    isLog2Transformed: bool | None
    sampleCount: int
    reason: str
    # Shown under the "already log2" checkbox when the values look like log10,
    # ln or count data; the detection itself cannot tell those from log2.
    scaleHint: str | None = None


class AnnotationImputationInfo(BaseModel):
    toolVersion: str | None = None
    mode: str = "none"
    applied: bool = False
    qValue: float | None = None
    adjustStd: float | None = None
    downShift: float | None = None
    width: float | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    sampleWise: bool | None = None
    sampleCount: int | None = None
    # Rows of the matrix that was imputed. Stored so the Imputation page can
    # state what is applied after a reload without re-running anything; `None`
    # on a record written before this field existed.
    rowCount: int | None = None
    missingBefore: int | None = None
    missingAfter: int | None = None


class PhosprotLineage(BaseModel):
    """Historical inputs at collapse time, never inferred from the current session."""
    model_config = {"extra": "forbid"}
    toolVersion: str
    aggregation: PhosprotAggregationMode
    source: Literal["filtered", "log2", "imputed"]
    coverageSource: Literal["filtered", "log2"]
    filter: AnnotationFilterConfig
    imputation: AnnotationImputationInfo | None
    siteCount: int = Field(ge=0)
    sampleCount: int = Field(ge=0)
    robustMinFraction: float | None = Field(default=None, gt=0, le=1)
    # Sites below this localization probability were left out of the collapse.
    localizationCutoff: float = Field(default=0.0, ge=0, le=1)


class AnnotationResultResponse(BaseModel):
    kind: AnnotationKind
    sourceRows: int
    sourceColumns: int
    metadataRows: int
    conditionCount: int
    sampleCount: int
    metadataPreview: list[dict[str, Any]]
    log2Rows: int
    log2Columns: int
    filteredRows: int
    filteredColumns: int
    filteredPreview: list[dict[str, Any]]
    isLog2Transformed: bool
    log2AutoDetected: bool = False
    metadataSource: MetadataSource = "manual"
    filter: AnnotationFilterConfig | None = None
    autoDetected: bool
    warnings: list[str] = Field(default_factory=list)
    imputation: AnnotationImputationInfo | None = None


class MetadataUploadResponse(BaseModel):
    kind: MetadataAnnotationKind
    profileName: str
    profileNames: list[str] = Field(default_factory=list)
    autoGeneratedProfileCount: int = 0
    filename: str
    rows: int
    columns: int
    createdAt: str
    preview: list[dict[str, Any]]


class PhosprotAggregateRequest(BaseModel):
    # Must match the UI default in frontend/src/features/metadata/AnnotationPage.tsx.
    mode: PhosprotAggregationMode = "robust_site_median"
    source: PhosprotAggregationSource = "non_imputed"
    # Only phosphosites with at least this localization probability are
    # collapsed; sites without a probability are excluded above 0.
    localizationCutoff: float = Field(default=0.0, ge=0, le=1)

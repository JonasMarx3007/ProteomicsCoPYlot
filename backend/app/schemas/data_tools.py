from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.annotation import AnnotationKind, ResolvedSource

# One vocabulary for every pipeline. "data" is the historical spelling and is
# still accepted on the wire; it resolves to each path's own default, which is
# why it is not a canonical value.


class HistogramBin(BaseModel):
    start: float
    end: float
    count: int


class ComparativeHistogramBin(BaseModel):
    start: float
    end: float
    leftCount: int
    rightCount: int


class CurvePoint(BaseModel):
    x: float
    y: float


class QQPoint(BaseModel):
    theoretical: float
    sample: float


class ValueDistributionStats(BaseModel):
    count: int
    missingCount: int
    min: float | None
    max: float | None
    mean: float | None
    median: float | None
    std: float | None


class DistributionSummaryResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: ResolvedSource
    sampleColumns: list[str]
    stats: ValueDistributionStats
    rowsWithMissing: int
    rowsWithoutMissing: int
    qqPlot: list[QQPoint]
    qqFitLine: list[CurvePoint]
    warnings: list[str] = Field(default_factory=list)


class IdTranslationRequest(BaseModel):
    kind: AnnotationKind
    column: str
    inputDb: str | None = None
    outputDb: str
    autoDetectInput: bool = False


class IdTranslationResponse(BaseModel):
    kind: AnnotationKind
    sourceColumn: str
    outputColumn: str
    inputDb: str
    outputDb: str
    translatedCount: int
    totalRows: int
    preview: list[dict[str, Any]]
    availableColumns: list[str]
    availableDatabases: list[str]
    downloadFilename: str
    warnings: list[str] = Field(default_factory=list)


class ConditionPaletteUpdateRequest(BaseModel):
    palette: dict[str, str] = Field(default_factory=dict)


class ConditionPaletteResponse(BaseModel):
    kind: AnnotationKind
    palette: dict[str, str] = Field(default_factory=dict)


class PhosphoLocalizationCutoffRequest(BaseModel):
    cutoff: float = Field(ge=0, le=1)


class PhosphoLocalizationCutoffResponse(BaseModel):
    """The session-wide phosphosite localization probability cutoff.

    `available` says whether the loaded phosphosite table has a
    PTM_localization column the cutoff can act on.
    """
    cutoff: float
    available: bool


class ImputationRunRequest(BaseModel):
    kind: AnnotationKind
    method: Literal["quantile", "numerical"] = "quantile"
    qValue: float = Field(default=0.01, ge=0.0, le=1.0)
    adjustStd: float = Field(default=0.3, ge=0.0)
    downShift: float = Field(default=1.8, ge=0.0)
    width: float = Field(default=0.3, ge=0.0)
    seed: int = Field(default=1337, ge=0, le=2_147_483_647)
    sampleWise: bool = True

    @model_validator(mode="after")
    def _spread_is_positive(self):
        # A spread of 0 gives every imputed value in a sample the same number, and
        # such constant replicates make the later t-test undefined.
        spread = self.adjustStd if self.method == "quantile" else self.width
        if spread <= 0:
            raise ValueError("Adjust standard deviation must be greater than 0.")
        return self


class ImputationResultResponse(BaseModel):
    kind: AnnotationKind
    method: Literal["quantile", "numerical"]
    sourceUsed: ResolvedSource
    rows: int
    columns: int
    sampleColumns: list[str]
    missingBefore: int
    missingAfter: int
    mean: float | None
    std: float | None
    quantile: float | None
    qValue: float
    adjustStd: float
    downShift: float
    width: float
    seed: int
    sampleWise: bool
    beforeMissingHistogram: list[ComparativeHistogramBin]
    overallHistogram: list[HistogramBin]
    normalFitCurve: list[CurvePoint]
    afterImputationHistogram: list[ComparativeHistogramBin]
    warnings: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]]

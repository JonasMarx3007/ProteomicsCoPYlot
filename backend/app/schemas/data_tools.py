from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind

DataSource = Literal["filtered", "log2", "raw"]


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
    sourceUsed: DataSource
    sampleColumns: list[str]
    stats: ValueDistributionStats
    rowsWithMissing: int
    rowsWithoutMissing: int
    qqPlot: list[QQPoint]
    qqFitLine: list[CurvePoint]
    warnings: list[str] = Field(default_factory=list)


class FirstDigitPoint(BaseModel):
    digit: int
    observed: float
    benford: float


class DuplicateFrequencyPoint(BaseModel):
    occurrences: int
    percentage: float


class VerificationSummaryResponse(BaseModel):
    kind: AnnotationKind
    sampleColumns: list[str]
    firstDigit: list[FirstDigitPoint]
    duplicateFrequency: list[DuplicateFrequencyPoint]
    numericValueCount: int


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


class ImputationRunRequest(BaseModel):
    kind: AnnotationKind
    qValue: float = Field(default=0.01, ge=0.0, le=1.0)
    adjustStd: float = Field(default=1.0, ge=0.0)
    seed: int = 1337
    sampleWise: bool = False


class ImputationResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: DataSource
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
    seed: int
    sampleWise: bool
    beforeMissingHistogram: list[ComparativeHistogramBin]
    overallHistogram: list[HistogramBin]
    normalFitCurve: list[CurvePoint]
    afterImputationHistogram: list[ComparativeHistogramBin]
    warnings: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]]

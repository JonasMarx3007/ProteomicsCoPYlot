from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import DataSource, HistogramBin


class SampleMetricPoint(BaseModel):
    sample: str
    value: float


class BoxplotPoint(BaseModel):
    sample: str
    min: float
    q1: float
    median: float
    q3: float
    max: float


class QcSummaryResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: DataSource
    sampleColumns: list[str]
    coverage: list[SampleMetricPoint]
    intensityHistogram: list[HistogramBin]
    boxplot: list[BoxplotPoint]
    cv: list[SampleMetricPoint]
    warnings: list[str] = Field(default_factory=list)


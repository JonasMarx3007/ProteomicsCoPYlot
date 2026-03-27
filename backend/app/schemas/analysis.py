from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import StatsIdentifier, StatsTestType

AnalysisSource = Literal["volcano", "volcano_control"]


class AnalysisVolcanoRequest(BaseModel):
    kind: AnnotationKind
    source: AnalysisSource = "volcano"
    condition1: str
    condition2: str
    condition1Control: str | None = None
    condition2Control: str | None = None
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False


class AnalysisVolcanoPoint(BaseModel):
    label: str
    selectionLabel: str
    uniprotAccession: str | None = None
    workflowLabel: str | None = None
    geneLabel: str | None = None
    significance: str
    log2FC: float
    negLog10P: float


class AnalysisVolcanoResponse(BaseModel):
    kind: AnnotationKind
    source: AnalysisSource
    labelColumn: str
    totalRows: int
    upregulatedCount: int
    downregulatedCount: int
    notSignificantCount: int
    points: list[AnalysisVolcanoPoint]
    warnings: list[str] = Field(default_factory=list)

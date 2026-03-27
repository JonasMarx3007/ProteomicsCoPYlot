from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind

StatsSource = Literal["filtered", "log2", "raw"]
StatsTestType = Literal["unpaired", "paired"]
StatsIdentifier = Literal["workflow", "genes"]
GseaDirection = Literal["up", "down"]
HeatmapValueType = Literal["log2", "z"]
EnrichmentSource = Literal["volcano", "volcano_control"]


class IdentifierOption(BaseModel):
    key: StatsIdentifier
    label: str


class StatisticalOptionsResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    availableConditions: list[str]
    availableIdentifiers: list[IdentifierOption]
    warnings: list[str] = Field(default_factory=list)


class VolcanoRequest(BaseModel):
    kind: AnnotationKind
    condition1: str
    condition2: str
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: list[str] = Field(default_factory=list)


class VolcanoControlRequest(BaseModel):
    kind: AnnotationKind
    condition1: str
    condition2: str
    condition1Control: str
    condition2Control: str
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: list[str] = Field(default_factory=list)


class VolcanoResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    labelColumn: str
    totalRows: int
    upregulatedCount: int
    downregulatedCount: int
    notSignificantCount: int
    rows: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)


class EnrichmentTerm(BaseModel):
    source: str
    termId: str
    name: str
    termSize: int
    intersectionSize: int
    hitPercent: float
    pValue: float
    adjPValue: float
    intersectingGenes: list[str]


class EnrichmentRequest(BaseModel):
    kind: AnnotationKind
    source: EnrichmentSource = "volcano"
    condition1: str
    condition2: str
    condition1Control: str | None = None
    condition2Control: str | None = None
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    topN: int = Field(default=10, ge=1, le=100)
    minTermSize: int = Field(default=20, ge=1)
    maxTermSize: int = Field(default=300, ge=1)


class EnrichmentResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    upGenes: list[str]
    downGenes: list[str]
    upTerms: list[EnrichmentTerm]
    downTerms: list[EnrichmentTerm]
    warnings: list[str] = Field(default_factory=list)


class PathwayOptionsResponse(BaseModel):
    pathways: list[str]


class SimulationRequest(BaseModel):
    kind: AnnotationKind
    condition1: str
    condition2: str
    pValueThreshold: float = Field(default=0.05, gt=0.0, le=1.0)
    log2fcThreshold: float = Field(default=1.0, ge=0.0)
    varianceMultiplier: float = Field(default=1.0, gt=0.0)
    sampleSizeOverride: int = Field(default=0, ge=0, le=100)


class SimulationResultResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: StatsSource
    totalRows: int
    upregulatedCount: int
    downregulatedCount: int
    notSignificantCount: int
    warnings: list[str] = Field(default_factory=list)

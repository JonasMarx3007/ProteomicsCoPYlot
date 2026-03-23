from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import StatsIdentifier, StatsTestType


class SummaryMetadataTable(BaseModel):
    kind: AnnotationKind
    available: bool
    rows: int = 0
    columns: int = 0
    columnNames: list[str] = Field(default_factory=list)
    table: list[dict[str, Any]] = Field(default_factory=list)


class SummaryTablesResponse(BaseModel):
    protein: SummaryMetadataTable
    phospho: SummaryMetadataTable


class SummaryVolcanoEntry(BaseModel):
    kind: AnnotationKind
    control: bool = False
    condition1: str
    condition2: str
    condition1Control: str | None = None
    condition2Control: str | None = None
    identifier: StatsIdentifier = "workflow"
    pValueThreshold: float = 0.05
    log2fcThreshold: float = 1.0
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: list[str] = Field(default_factory=list)


class SummaryReportContext(BaseModel):
    qcSettings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    volcanoEntries: list[SummaryVolcanoEntry] = Field(default_factory=list)


class SummaryReportRequest(BaseModel):
    title: str = ""
    author: str = ""
    textEntries: dict[str, str] = Field(default_factory=dict)
    reportContext: SummaryReportContext | None = None


class SummaryReportResponse(BaseModel):
    fileName: str
    html: str
    warnings: list[str] = Field(default_factory=list)

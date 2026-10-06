from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind, DataSource
from app.schemas.stats import StatsIdentifier, StatsTestType, VolcanoRenderType


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
    dataSource: DataSource = "data"
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
    # Which renderer this comparison was added with. Per entry rather than per
    # report, because the choice is about what a particular figure is for: a
    # volcano being screened for hits wants hover text, the one going into the
    # paper wants print styling, and one report can legitimately hold both.
    # Defaults to Interactive, which is what every entry logged before this
    # existed was rendered as.
    renderType: VolcanoRenderType = "Interactive"
    # Only the static renderer draws labels; ignored when renderType is
    # Interactive, where hovering a point names it.
    labelTopUp: int = Field(default=0, ge=0, le=200)
    labelTopDown: int = Field(default=0, ge=0, le=200)


class SummaryReportContext(BaseModel):
    completenessSettings: dict[str, Any] = Field(default_factory=dict)
    qcSettings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    volcanoEntries: list[SummaryVolcanoEntry] = Field(default_factory=list)
    advancedPlotMode: bool = False
    advancedPlotSettingsByKey: dict[str, dict[str, Any]] = Field(default_factory=dict)
    qcAdvancedSettingsByTab: dict[str, dict[str, Any]] = Field(default_factory=dict)
    completenessAdvancedSettingsByTab: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SummaryReportRequest(BaseModel):
    title: str = ""
    author: str = ""
    textEntries: dict[str, str] = Field(default_factory=dict)
    reportContext: SummaryReportContext | None = None


class SummaryReportResponse(BaseModel):
    fileName: str
    html: str
    warnings: list[str] = Field(default_factory=list)
    notebookToken: str | None = None
    notebookError: str | None = None
    # Report sections the notebook leaves out because their export could not be prepared.
    notebookOmitted: list[str] = Field(default_factory=list)

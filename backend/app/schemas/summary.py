from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SummaryTableBlock(BaseModel):
    key: str
    title: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    rowCount: int = 0
    available: bool = False
    message: str | None = None


class SummarySectionInfo(BaseModel):
    key: str
    title: str
    group: str
    description: str


class SummarySectionNote(BaseModel):
    above: str = ""
    below: str = ""


class SummaryOverviewResponse(BaseModel):
    tables: list[SummaryTableBlock] = Field(default_factory=list)
    availableSections: list[SummarySectionInfo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggestedFilename: str = "proteomicscopylot_summary_report.html"


class SummaryReportRequest(BaseModel):
    title: str = ""
    author: str = ""
    introduction: str = ""
    notes: dict[str, SummarySectionNote] = Field(default_factory=dict)
    includeMetadataTables: bool = True

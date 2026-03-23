from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.annotation import AnnotationKind


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


class SummaryReportRequest(BaseModel):
    title: str = ""
    author: str = ""
    textEntries: dict[str, str] = Field(default_factory=dict)


class SummaryReportResponse(BaseModel):
    fileName: str
    html: str
    warnings: list[str] = Field(default_factory=list)

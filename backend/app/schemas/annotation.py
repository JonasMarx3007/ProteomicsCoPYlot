from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnnotationKind = Literal["protein", "phospho"]
FilterMode = Literal["per_group", "in_at_least_one_group"]


class ConditionAssignment(BaseModel):
    name: str = Field(min_length=1)
    columns: list[str] = Field(default_factory=list)


class AnnotationFilterConfig(BaseModel):
    minPresent: int = Field(default=3, ge=0)
    mode: FilterMode = "per_group"


class AnnotationGenerateRequest(BaseModel):
    kind: AnnotationKind
    conditions: list[ConditionAssignment] = Field(default_factory=list)
    isLog2Transformed: bool = True
    filter: AnnotationFilterConfig | None = None


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
    filter: AnnotationFilterConfig | None = None
    autoDetected: bool
    warnings: list[str] = Field(default_factory=list)


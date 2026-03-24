from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnnotationKind = Literal["protein", "phospho", "phosprot"]
MetadataAnnotationKind = Literal["protein", "phospho"]
FilterMode = Literal["per_group", "in_at_least_one_group"]
MetadataSource = Literal["manual", "auto", "uploaded", "shared_phospho"]
PhosprotAggregationMode = Literal[
    "sum_mean_impute",
    "sum_propagate_na",
    "sum_ignore_na",
    "mean",
]


class ConditionAssignment(BaseModel):
    name: str = Field(min_length=1)
    columns: list[str] = Field(default_factory=list)


class AnnotationFilterConfig(BaseModel):
    minPresent: int = Field(default=0, ge=0)
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
    metadataSource: MetadataSource = "manual"
    filter: AnnotationFilterConfig | None = None
    autoDetected: bool
    warnings: list[str] = Field(default_factory=list)


class MetadataUploadResponse(BaseModel):
    kind: MetadataAnnotationKind
    filename: str
    rows: int
    columns: int
    createdAt: str
    preview: list[dict[str, Any]]


class PhosprotAggregateRequest(BaseModel):
    mode: PhosprotAggregationMode = "sum_mean_impute"

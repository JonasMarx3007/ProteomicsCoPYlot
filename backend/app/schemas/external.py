from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PeptideCollapseRequest(BaseModel):
    inputPath: str
    outputPath: str | None = None
    cutoff: float = Field(default=0.0, ge=0.0, le=1.0)
    collapseVersion: Literal["fixed", "newest", "legacy"] = "fixed"


class PeptideCollapseResponse(BaseModel):
    success: bool
    inputPath: str
    outputPath: str | None
    cutoff: float
    collapseVersion: Literal["fixed", "newest", "legacy"]
    rows: int | None = None
    columns: int | None = None
    columnNames: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    logs: str
    error: str | None = None

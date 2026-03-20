from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PeptideSpecies = Literal["human", "mouse"]


class PeptideMetadataResponse(BaseModel):
    filename: str
    rows: int
    columns: int
    createdAt: str
    preview: list[dict[str, Any]] = Field(default_factory=list)


class PeptideOverviewResponse(BaseModel):
    filename: str
    path: str
    rows: int
    columns: int
    columnNames: list[str] = Field(default_factory=list)
    availableProteins: list[str] = Field(default_factory=list)
    metadataLoaded: bool = False
    metadataFilename: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PeptideCoverageResponse(BaseModel):
    protein: str
    species: PeptideSpecies
    coveragePercent: float
    matchingPeptideCount: int
    sequenceText: str
    warnings: list[str] = Field(default_factory=list)

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.annotation import ConditionAssignment

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
    availableSamples: list[str] = Field(default_factory=list)
    availableProteins: list[str] = Field(default_factory=list)
    metadataLoaded: bool = False
    metadataFilename: str | None = None
    warnings: list[str] = Field(default_factory=list)


class PeptideQuantityOptionsResponse(BaseModel):
    columns: list[str] = Field(default_factory=list)
    defaultColumn: str | None = None
    requiresSelection: bool = False


class PeptideMetadataGenerateRequest(BaseModel):
    conditions: list[ConditionAssignment] = Field(default_factory=list)


class PeptideCoverageResponse(BaseModel):
    protein: str
    species: PeptideSpecies
    coveragePercent: float
    # Peptides of the protein group that occur in the selected sequence; the
    # coverage percentage is built from these.
    matchingPeptideCount: int
    # All peptides the report assigns to the protein group.
    assignedPeptideCount: int
    # Assigned peptides that do not occur in the selected sequence (first 20).
    unmappedPeptides: list[str] = Field(default_factory=list)
    sequenceText: str
    warnings: list[str] = Field(default_factory=list)

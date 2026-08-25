from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

RestoreDatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]


class RestoreExportRequest(BaseModel):
    uiState: dict[str, Any] | None = None
    portable: bool = False


class RestoreMissingFile(BaseModel):
    packageName: str
    kind: RestoreDatasetKind
    filename: str | None = None
    expectedPath: str | None = None
    message: str


class RestoreImportResponse(BaseModel):
    ok: bool
    uiState: dict[str, Any] | None = None
    warnings: list[str]
    missingFiles: list[RestoreMissingFile]
    restoredDatasets: list[str]
    restoredAnnotations: list[str]

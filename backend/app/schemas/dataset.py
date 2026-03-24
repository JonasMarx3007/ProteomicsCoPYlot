from typing import Any, Literal

from pydantic import BaseModel

DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
TableDatasetKind = Literal["protein", "phospho", "phosprot"]


class DatasetPreviewResponse(BaseModel):
    filename: str
    kind: TableDatasetKind
    format: str
    rows: int
    columns: int
    columnNames: list[str]
    preview: list[dict[str, Any]]


class PeptidePathResponse(BaseModel):
    filename: str
    kind: Literal["peptide"]
    format: str
    path: str
    rows: int
    columns: int
    columnNames: list[str]
    preview: list[dict[str, Any]]


class CurrentDatasetsResponse(BaseModel):
    protein: DatasetPreviewResponse | None
    phospho: DatasetPreviewResponse | None
    phosprot: DatasetPreviewResponse | None
    peptide: PeptidePathResponse | None


class PeptidePathRequest(BaseModel):
    path: str

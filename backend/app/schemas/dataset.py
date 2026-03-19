from typing import Literal, Any
from pydantic import BaseModel

DatasetKind = Literal["protein", "phospho"]

class DatasetPreviewResponse(BaseModel):
    datasetId: str
    filename: str
    kind: DatasetKind
    format: str
    rows: int
    columns: int
    columnNames: list[str]
    preview: list[dict[str, Any]]
from __future__ import annotations

import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.summary import SummaryMetadataTable, SummaryTablesResponse
from app.services.annotation_store import get_annotation


def _metadata_table(kind: AnnotationKind) -> SummaryMetadataTable:
    stored = get_annotation(kind)
    if stored is None or stored.metadata.empty:
        return SummaryMetadataTable(kind=kind, available=False)

    table = stored.metadata.copy().where(pd.notna(stored.metadata), None)
    return SummaryMetadataTable(
        kind=kind,
        available=True,
        rows=len(table),
        columns=len(table.columns),
        columnNames=[str(column) for column in table.columns],
        table=table.to_dict(orient="records"),
    )


def summary_tables() -> SummaryTablesResponse:
    return SummaryTablesResponse(
        protein=_metadata_table("protein"),
        phospho=_metadata_table("phospho"),
    )

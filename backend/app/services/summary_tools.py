from __future__ import annotations


from app.schemas.annotation import AnnotationKind
from app.schemas.summary import SummaryMetadataTable, SummaryTablesResponse
from app.services.annotation_store import get_annotation
from app.services.runtime_cache import apply_cached_wrappers
from app.services.json_records import json_records


def _metadata_table(kind: AnnotationKind) -> SummaryMetadataTable:
    stored = get_annotation(kind)
    if stored is None or stored.metadata.empty:
        return SummaryMetadataTable(kind=kind, available=False)

    table = stored.metadata
    return SummaryMetadataTable(
        kind=kind,
        available=True,
        rows=len(table),
        columns=len(table.columns),
        columnNames=[str(column) for column in table.columns],
        table=json_records(table),
    )


def summary_tables() -> SummaryTablesResponse:
    return SummaryTablesResponse(
        protein=_metadata_table("protein"),
        phospho=_metadata_table("phospho"),
    )


apply_cached_wrappers(globals(), ["summary_tables"])

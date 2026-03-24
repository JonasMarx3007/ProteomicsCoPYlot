from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.schemas.annotation import MetadataAnnotationKind


@dataclass
class StoredUploadedMetadata:
    kind: MetadataAnnotationKind
    filename: str
    frame: pd.DataFrame
    created_at: str


_UPLOADED_METADATA: dict[MetadataAnnotationKind, StoredUploadedMetadata | None] = {
    "protein": None,
    "phospho": None,
}


def save_uploaded_metadata(
    kind: MetadataAnnotationKind,
    filename: str,
    frame: pd.DataFrame,
) -> StoredUploadedMetadata:
    stored = StoredUploadedMetadata(
        kind=kind,
        filename=filename,
        frame=frame.copy(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _UPLOADED_METADATA[kind] = stored
    return stored


def get_uploaded_metadata(kind: MetadataAnnotationKind) -> StoredUploadedMetadata | None:
    return _UPLOADED_METADATA.get(kind)


def clear_uploaded_metadata(kind: MetadataAnnotationKind) -> None:
    _UPLOADED_METADATA[kind] = None

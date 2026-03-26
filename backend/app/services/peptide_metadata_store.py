from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.services.runtime_cache import invalidate_runtime_cache


@dataclass
class StoredPeptideMetadata:
    filename: str
    frame: pd.DataFrame
    created_at: str


_CURRENT_METADATA: StoredPeptideMetadata | None = None


def save_peptide_metadata(filename: str, frame: pd.DataFrame) -> StoredPeptideMetadata:
    global _CURRENT_METADATA
    _CURRENT_METADATA = StoredPeptideMetadata(
        filename=filename,
        frame=frame.copy(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    invalidate_runtime_cache("peptide-metadata:updated")
    return _CURRENT_METADATA


def get_peptide_metadata() -> StoredPeptideMetadata | None:
    return _CURRENT_METADATA


def clear_peptide_metadata() -> None:
    global _CURRENT_METADATA
    _CURRENT_METADATA = None
    invalidate_runtime_cache("peptide-metadata:cleared")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd


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
    return _CURRENT_METADATA


def get_peptide_metadata() -> StoredPeptideMetadata | None:
    return _CURRENT_METADATA


def clear_peptide_metadata() -> None:
    global _CURRENT_METADATA
    _CURRENT_METADATA = None

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id


@dataclass
class StoredPeptideMetadata:
    filename: str
    frame: pd.DataFrame
    created_at: str


_METADATA_BY_SESSION: dict[str, StoredPeptideMetadata | None] = {}


def save_peptide_metadata(filename: str, frame: pd.DataFrame) -> StoredPeptideMetadata:
    stored = StoredPeptideMetadata(
        filename=filename,
        frame=frame.copy(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _METADATA_BY_SESSION[get_session_id()] = stored
    invalidate_runtime_cache("peptide-metadata:updated")
    return stored


def get_peptide_metadata() -> StoredPeptideMetadata | None:
    return _METADATA_BY_SESSION.get(get_session_id())


def clear_peptide_metadata(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _METADATA_BY_SESSION.clear()
    else:
        _METADATA_BY_SESSION[get_session_id()] = None
    invalidate_runtime_cache("peptide-metadata:cleared")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.services.dataset_store import get_active_package
from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id


@dataclass
class StoredPeptideMetadata:
    filename: str
    frame: pd.DataFrame
    created_at: str


_METADATA_BY_SESSION: dict[str, dict[str, StoredPeptideMetadata | None]] = {}


def _package_state() -> dict[str, StoredPeptideMetadata | None]:
    session_id = get_session_id()
    if session_id not in _METADATA_BY_SESSION:
        _METADATA_BY_SESSION[session_id] = {}
    return _METADATA_BY_SESSION[session_id]


def save_peptide_metadata(
    filename: str,
    frame: pd.DataFrame,
    *,
    package_name: str | None = None,
) -> StoredPeptideMetadata:
    stored = StoredPeptideMetadata(
        filename=filename,
        frame=frame.copy(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    resolved_package = str(package_name or "").strip() or get_active_package()
    _package_state()[resolved_package] = stored
    invalidate_runtime_cache("peptide-metadata:updated")
    return stored


def get_peptide_metadata(*, package_name: str | None = None) -> StoredPeptideMetadata | None:
    resolved_package = str(package_name or "").strip() or get_active_package()
    return _package_state().get(resolved_package)


def clear_peptide_metadata(
    *,
    all_sessions: bool = False,
    active_package_only: bool = False,
) -> None:
    if all_sessions:
        _METADATA_BY_SESSION.clear()
    elif active_package_only:
        _package_state()[get_active_package()] = None
    else:
        _METADATA_BY_SESSION.pop(get_session_id(), None)
    invalidate_runtime_cache("peptide-metadata:cleared", all_sessions=all_sessions)


def snapshot_peptide_metadata_session_state():
    """Detach-safe reference used before the session entry is atomically replaced."""
    return _METADATA_BY_SESSION.get(get_session_id())


def restore_peptide_metadata_session_state(snapshot) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _METADATA_BY_SESSION.pop(session_id, None)
    else:
        _METADATA_BY_SESSION[session_id] = snapshot
    invalidate_runtime_cache("peptide-metadata:transaction-restored")

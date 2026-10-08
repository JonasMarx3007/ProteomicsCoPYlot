from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id
from app.schemas.annotation import PhosprotLineage, IdentifierTranslationStep

DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
TableDatasetKind = Literal["protein", "phospho", "phosprot"]

DEFAULT_PACKAGE_NAME = "Data"


@dataclass
class StoredTableDataset:
    filename: str
    kind: TableDatasetKind
    frame: pd.DataFrame
    source_path: str | None = None
    phosprot_aggregation: str | None = None
    phosprot_lineage: PhosprotLineage | None = None
    id_translations: list[IdentifierTranslationStep] = field(default_factory=list)


@dataclass
class StoredPeptideDataset:
    filename: str
    kind: Literal["peptide"]
    path: str


@dataclass
class _DatasetSessionState:
    datasets_by_package: dict[str, dict[str, StoredTableDataset | StoredPeptideDataset | None]]
    active_package: str


def _empty_package_state() -> dict[str, StoredTableDataset | StoredPeptideDataset | None]:
    return {
        "protein": None,
        "phospho": None,
        "phosprot": None,
        "peptide": None,
    }


def _new_session_state() -> _DatasetSessionState:
    return _DatasetSessionState(
        datasets_by_package={DEFAULT_PACKAGE_NAME: _empty_package_state()},
        active_package=DEFAULT_PACKAGE_NAME,
    )


_DATASET_SESSIONS: dict[str, _DatasetSessionState] = {}


def _session_state() -> _DatasetSessionState:
    session_id = get_session_id()
    state = _DATASET_SESSIONS.get(session_id)
    if state is None:
        state = _new_session_state()
        _DATASET_SESSIONS[session_id] = state
    return state


def _normalize_package_name(package_name: str | None) -> str:
    text = str(package_name or "").strip()
    if text:
        return text
    state = _session_state()
    return state.active_package or DEFAULT_PACKAGE_NAME


def _ensure_package(package_name: str) -> str:
    resolved = _normalize_package_name(package_name)
    state = _session_state()
    if resolved not in state.datasets_by_package:
        state.datasets_by_package[resolved] = _empty_package_state()
        invalidate_runtime_cache(f"dataset-package:{resolved}:created")
    return resolved


def _package_state(package_name: str | None = None) -> dict[str, StoredTableDataset | StoredPeptideDataset | None]:
    resolved = _ensure_package(_normalize_package_name(package_name))
    return _session_state().datasets_by_package[resolved]


def get_active_package() -> str:
    return _session_state().active_package


def set_active_package(package_name: str) -> str:
    state = _session_state()
    resolved = _ensure_package(package_name)
    state.active_package = resolved
    invalidate_runtime_cache(f"dataset-package:{resolved}:active")
    return resolved


def create_package(package_name: str) -> str:
    return _ensure_package(package_name)


def rename_package(old_name: str, new_name: str) -> str:
    state = _session_state()
    old_resolved = _normalize_package_name(old_name)
    new_resolved = _normalize_package_name(new_name)
    if not old_resolved:
        raise ValueError("Original dataset package name must not be empty.")
    if not new_resolved:
        raise ValueError("New dataset package name must not be empty.")
    if old_resolved not in state.datasets_by_package:
        raise ValueError(f"Dataset package '{old_resolved}' does not exist.")
    if new_resolved in state.datasets_by_package and new_resolved != old_resolved:
        raise ValueError(f"Dataset package '{new_resolved}' already exists.")
    if old_resolved == new_resolved:
        return old_resolved

    state.datasets_by_package[new_resolved] = state.datasets_by_package.pop(old_resolved)
    if state.active_package == old_resolved:
        state.active_package = new_resolved
    invalidate_runtime_cache(f"dataset-package:{old_resolved}:renamed:{new_resolved}")
    return new_resolved


def session_has_datasets() -> bool:
    """True when this session holds at least one stored dataset.

    Unlike list_packages() this never answers with the default package name for
    an empty session, and it does not create a session entry by asking.
    """
    state = _DATASET_SESSIONS.get(get_session_id())
    if state is None:
        return False
    return any(
        package_state.get(kind) is not None
        for package_state in state.datasets_by_package.values()
        for kind in ("protein", "phospho", "phosprot", "peptide")
    )


def list_packages(*, include_empty: bool = False) -> list[str]:
    state = _session_state()
    if include_empty:
        packages = sorted(state.datasets_by_package.keys(), key=lambda value: value.lower())
        active = get_active_package()
        if active in packages:
            packages = [active] + [value for value in packages if value != active]
        return packages
    names: list[str] = []
    for name, package_state in state.datasets_by_package.items():
        if any(package_state.get(kind) is not None for kind in ("protein", "phospho", "phosprot", "peptide")):
            names.append(name)
    if not names:
        return [get_active_package()]
    names_sorted = sorted(names, key=lambda value: value.lower())
    active = get_active_package()
    if active in names_sorted:
        names_sorted = [active] + [value for value in names_sorted if value != active]
    return names_sorted


def save_table_dataset(
    filename: str,
    kind: TableDatasetKind,
    frame: pd.DataFrame,
    *,
    package_name: str | None = None,
    source_path: str | None = None,
    phosprot_aggregation: str | None = None,
    phosprot_lineage: PhosprotLineage | None = None,
    id_translations: list[IdentifierTranslationStep] | None = None,
) -> StoredTableDataset:
    resolved_package = _normalize_package_name(package_name)
    state = _package_state(resolved_package)

    stored = StoredTableDataset(
        filename=filename,
        kind=kind,
        frame=frame,
        source_path=str(source_path).strip() or None if source_path is not None else None,
        phosprot_aggregation=phosprot_aggregation,
        phosprot_lineage=phosprot_lineage.model_copy(deep=True) if phosprot_lineage else None,
        id_translations=[step.model_copy(deep=True) for step in id_translations or []],
    )
    state[kind] = stored
    invalidate_runtime_cache(f"dataset:{resolved_package}:{kind}:updated")
    return stored


def save_peptide_path(path: str, *, package_name: str | None = None) -> StoredPeptideDataset:
    resolved_package = _normalize_package_name(package_name)
    state = _package_state(resolved_package)

    normalized = path.strip()
    filename = normalized.replace("\\", "/").split("/")[-1]

    stored = StoredPeptideDataset(
        filename=filename,
        kind="peptide",
        path=normalized,
    )
    state["peptide"] = stored
    invalidate_runtime_cache(f"dataset:{resolved_package}:peptide:updated")
    return stored


def get_current_dataset(kind: DatasetKind, *, package_name: str | None = None):
    state = _package_state(package_name)
    return state.get(kind)


def get_all_current_datasets(*, package_name: str | None = None):
    state = _package_state(package_name)
    return state.copy()


def reset_all_datasets(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _DATASET_SESSIONS.clear()
    else:
        _DATASET_SESSIONS.pop(get_session_id(), None)
    invalidate_runtime_cache("dataset:reset-all", all_sessions=all_sessions)


def snapshot_dataset_session_state() -> _DatasetSessionState | None:
    """Detach-safe reference used before the session entry is atomically replaced."""
    return _DATASET_SESSIONS.get(get_session_id())


def restore_dataset_session_state(snapshot: _DatasetSessionState | None) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _DATASET_SESSIONS.pop(session_id, None)
    else:
        _DATASET_SESSIONS[session_id] = snapshot
    invalidate_runtime_cache("dataset:transaction-restored")

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.services.runtime_cache import invalidate_runtime_cache

DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
TableDatasetKind = Literal["protein", "phospho", "phosprot"]

DEFAULT_PACKAGE_NAME = "Data"


@dataclass
class StoredTableDataset:
    filename: str
    kind: TableDatasetKind
    frame: pd.DataFrame
    suggested_is_log2_transformed: bool = True


@dataclass
class StoredPeptideDataset:
    filename: str
    kind: Literal["peptide"]
    path: str


def _empty_package_state() -> dict[str, StoredTableDataset | StoredPeptideDataset | None]:
    return {
        "protein": None,
        "phospho": None,
        "phosprot": None,
        "peptide": None,
    }


_DATASETS_BY_PACKAGE: dict[str, dict[str, StoredTableDataset | StoredPeptideDataset | None]] = {
    DEFAULT_PACKAGE_NAME: _empty_package_state(),
}
_ACTIVE_PACKAGE = DEFAULT_PACKAGE_NAME


def _normalize_package_name(package_name: str | None) -> str:
    text = str(package_name or "").strip()
    if not text:
        return _ACTIVE_PACKAGE or DEFAULT_PACKAGE_NAME
    return text


def _ensure_package(package_name: str) -> str:
    resolved = _normalize_package_name(package_name)
    if resolved not in _DATASETS_BY_PACKAGE:
        _DATASETS_BY_PACKAGE[resolved] = _empty_package_state()
        invalidate_runtime_cache(f"dataset-package:{resolved}:created")
    return resolved


def _package_state(package_name: str | None = None) -> dict[str, StoredTableDataset | StoredPeptideDataset | None]:
    resolved = _ensure_package(_normalize_package_name(package_name))
    return _DATASETS_BY_PACKAGE[resolved]


def _guess_log2_transformed(frame: pd.DataFrame) -> bool:
    numeric = frame.select_dtypes(include=["number"]).replace([np.inf, -np.inf], np.nan)
    if numeric.empty:
        return True

    values = numeric.to_numpy(dtype=float, copy=False).ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return True

    if finite.size > 200_000:
        rng = np.random.default_rng(187)
        finite = rng.choice(finite, 200_000, replace=False)

    q50 = float(np.nanquantile(finite, 0.50))
    q95 = float(np.nanquantile(finite, 0.95))
    q99 = float(np.nanquantile(finite, 0.99))
    vmax = float(np.nanmax(finite))

    if q95 > 50 or q99 > 100 or vmax > 200:
        return False
    return q50 <= 35 and q95 <= 45 and q99 <= 60


def get_active_package() -> str:
    return _ACTIVE_PACKAGE


def set_active_package(package_name: str) -> str:
    global _ACTIVE_PACKAGE
    resolved = _ensure_package(package_name)
    _ACTIVE_PACKAGE = resolved
    invalidate_runtime_cache(f"dataset-package:{resolved}:active")
    return resolved


def create_package(package_name: str) -> str:
    return _ensure_package(package_name)


def rename_package(old_name: str, new_name: str) -> str:
    global _ACTIVE_PACKAGE
    old_resolved = _normalize_package_name(old_name)
    new_resolved = _normalize_package_name(new_name)
    if not old_resolved:
        raise ValueError("Original dataset package name must not be empty.")
    if not new_resolved:
        raise ValueError("New dataset package name must not be empty.")
    if old_resolved not in _DATASETS_BY_PACKAGE:
        raise ValueError(f"Dataset package '{old_resolved}' does not exist.")
    if new_resolved in _DATASETS_BY_PACKAGE and new_resolved != old_resolved:
        raise ValueError(f"Dataset package '{new_resolved}' already exists.")
    if old_resolved == new_resolved:
        return old_resolved

    _DATASETS_BY_PACKAGE[new_resolved] = _DATASETS_BY_PACKAGE.pop(old_resolved)
    if _ACTIVE_PACKAGE == old_resolved:
        _ACTIVE_PACKAGE = new_resolved
    invalidate_runtime_cache(f"dataset-package:{old_resolved}:renamed:{new_resolved}")
    return new_resolved


def list_packages(*, include_empty: bool = False) -> list[str]:
    if include_empty:
        names = sorted(_DATASETS_BY_PACKAGE.keys(), key=lambda value: value.lower())
        active = get_active_package()
        if active in names:
            names = [active] + [value for value in names if value != active]
        return names
    names: list[str] = []
    for name, state in _DATASETS_BY_PACKAGE.items():
        if any(state.get(kind) is not None for kind in ("protein", "phospho", "phosprot", "peptide")):
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
) -> StoredTableDataset:
    resolved_package = _normalize_package_name(package_name)
    state = _package_state(resolved_package)

    stored = StoredTableDataset(
        filename=filename,
        kind=kind,
        frame=frame,
        suggested_is_log2_transformed=_guess_log2_transformed(frame),
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


def clear_dataset(kind: DatasetKind, *, package_name: str | None = None) -> None:
    resolved_package = _normalize_package_name(package_name)
    state = _package_state(resolved_package)
    state[kind] = None
    invalidate_runtime_cache(f"dataset:{resolved_package}:{kind}:cleared")

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from app.services.runtime_cache import invalidate_runtime_cache

DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
TableDatasetKind = Literal["protein", "phospho", "phosprot"]


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


_CURRENT_DATASETS: dict[str, StoredTableDataset | StoredPeptideDataset | None] = {
    "protein": None,
    "phospho": None,
    "phosprot": None,
    "peptide": None,
}


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


def save_table_dataset(
    filename: str,
    kind: TableDatasetKind,
    frame: pd.DataFrame,
) -> StoredTableDataset:
    stored = StoredTableDataset(
        filename=filename,
        kind=kind,
        frame=frame,
        suggested_is_log2_transformed=_guess_log2_transformed(frame),
    )
    _CURRENT_DATASETS[kind] = stored
    invalidate_runtime_cache(f"dataset:{kind}:updated")
    return stored


def save_peptide_path(path: str) -> StoredPeptideDataset:
    normalized = path.strip()
    filename = normalized.replace("\\", "/").split("/")[-1]

    stored = StoredPeptideDataset(
        filename=filename,
        kind="peptide",
        path=normalized,
    )
    _CURRENT_DATASETS["peptide"] = stored
    invalidate_runtime_cache("dataset:peptide:updated")
    return stored


def get_current_dataset(kind: DatasetKind):
    return _CURRENT_DATASETS.get(kind)


def get_all_current_datasets():
    return _CURRENT_DATASETS.copy()


def clear_dataset(kind: DatasetKind) -> None:
    _CURRENT_DATASETS[kind] = None
    invalidate_runtime_cache(f"dataset:{kind}:cleared")

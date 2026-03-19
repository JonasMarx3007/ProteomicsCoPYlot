from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

DatasetKind = Literal["protein", "phospho", "peptide"]
TableDatasetKind = Literal["protein", "phospho"]


@dataclass
class StoredTableDataset:
    filename: str
    kind: TableDatasetKind
    frame: pd.DataFrame


@dataclass
class StoredPeptideDataset:
    filename: str
    kind: Literal["peptide"]
    path: str


_CURRENT_DATASETS: dict[str, StoredTableDataset | StoredPeptideDataset | None] = {
    "protein": None,
    "phospho": None,
    "peptide": None,
}


def save_table_dataset(
    filename: str,
    kind: TableDatasetKind,
    frame: pd.DataFrame,
) -> StoredTableDataset:
    stored = StoredTableDataset(filename=filename, kind=kind, frame=frame)
    _CURRENT_DATASETS[kind] = stored
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
    return stored


def get_current_dataset(kind: DatasetKind):
    return _CURRENT_DATASETS.get(kind)


def get_all_current_datasets():
    return _CURRENT_DATASETS.copy()
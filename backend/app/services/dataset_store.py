from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import pandas as pd

DatasetKind = Literal["protein", "phospho"]


@dataclass
class StoredDataset:
    dataset_id: str
    filename: str
    kind: DatasetKind
    frame: pd.DataFrame


_DATASETS: dict[str, StoredDataset] = {}


def save_dataset(filename: str, kind: DatasetKind, frame: pd.DataFrame) -> StoredDataset:
    dataset_id = f"ds_{uuid4().hex[:12]}"
    stored = StoredDataset(
        dataset_id=dataset_id,
        filename=filename,
        kind=kind,
        frame=frame,
    )
    _DATASETS[dataset_id] = stored
    return stored


def get_dataset(dataset_id: str) -> StoredDataset | None:
    return _DATASETS.get(dataset_id)
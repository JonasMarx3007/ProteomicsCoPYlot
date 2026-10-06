from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services import stats_tools as st
from app.services.annotation_store import (
    get_annotation,
    reset_all_annotations,
    save_annotation,
)
from app.services.dataset_store import reset_all_datasets, save_table_dataset
from app.services.runtime_cache import invalidate_runtime_cache

SAMPLES = [f"{c}{i}" for c in ("WT", "KO") for i in (1, 2, 3)]


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(4)
    baseline = rng.normal(22, 2, 600)
    frame = pd.DataFrame({s: baseline + rng.normal(0, 0.5, 600) for s in SAMPLES})
    frame.iloc[:60, 3:] += 1.4
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(600)])
    metadata = pd.DataFrame({"sample": SAMPLES, "condition": [s[:2] for s in SAMPLES]})
    return frame, metadata


def _volcano(tag: str) -> pd.DataFrame:
    invalidate_runtime_cache(tag)
    return st._volcano_dataframe(
        kind="protein", condition1="WT", condition2="KO", identifier="workflow",
        p_value_threshold=0.05, log2fc_threshold=1.0,
        test_type="unpaired_welch", use_uncorrected=False, data_source="data",
    )[2]


def _digest(frame: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(frame, index=False).values.tobytes()
    ).hexdigest()


@pytest.fixture
def loaded(tmp_path):
    reset_all_annotations()
    reset_all_datasets()
    frame, metadata = _fixture()
    path = tmp_path / "protein.tsv"
    frame.to_csv(path, sep="\t", index=False)
    save_table_dataset(filename=str(path), kind="protein", frame=frame)
    save_annotation(
        kind="protein", source_data=frame, metadata=metadata, log2_data=frame,
        filtered_data=frame, is_log2_transformed=True, metadata_source="manual",
        filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[],
    )
    try:
        yield frame, metadata, path
    finally:
        reset_all_annotations()
        reset_all_datasets()


def test_rerunning_the_same_analysis_is_bit_identical(loaded) -> None:
    first = _volcano("reproducible-1")
    second = _volcano("reproducible-2")
    assert _digest(first) == _digest(second), "the same analysis gave two different frames"


def test_the_welch_test_is_not_accidentally_random(loaded) -> None:
    first = _volcano("stable-1")["adj_pval"].to_numpy(dtype=float)
    second = _volcano("stable-2")["adj_pval"].to_numpy(dtype=float)
    assert np.array_equal(first, second, equal_nan=True)


def test_the_analysis_survives_a_save_and_restore(loaded) -> None:
    before = _volcano("restore-before")

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        exported = client.post("/api/restore/export", json={})
        assert exported.status_code == 200, exported.text[:200]
        reset_all_annotations()
        reset_all_datasets()
        assert get_annotation("protein") is None, "the wipe did not take effect"

        imported = client.post(
            "/api/restore/import",
            files={"stateFile": ("state.copylot", exported.content, "application/octet-stream")},
        )
        assert imported.status_code == 200, imported.text[:300]

    assert get_annotation("protein") is not None, "restore did not reinstate the annotation"
    after = _volcano("restore-after")

    assert len(after) == len(before)
    assert list(after["ProteinNames"]) == list(before["ProteinNames"]), (
        "restore changed which features are present, or their order"
    )
    for column in ("log2FC", "pval", "adj_pval"):
        assert np.allclose(
            after[column].to_numpy(dtype=float),
            before[column].to_numpy(dtype=float),
            rtol=0, atol=1e-9, equal_nan=True,
        ), f"{column} changed by more than text round-tripping can explain"


def test_the_restored_data_matches_the_file_on_disk(loaded) -> None:
    frame, _, path = loaded
    on_disk = pd.read_csv(path, sep="\t")
    annotation = get_annotation("protein")
    assert np.allclose(
        annotation.source_data[SAMPLES].to_numpy(dtype=float),
        on_disk[SAMPLES].to_numpy(dtype=float),
    )

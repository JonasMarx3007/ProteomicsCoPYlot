"""A log2 upload with many exact zeros far below its other values gets a warning.

In a log2 matrix 0 is a measurement (an intensity of 1). Exports that write 0
for "not measured" turn every such cell into an extreme low value: in a null
simulation around log2 22 with 15 % zeros, half the rows came out with
|log2FC| > 5. The annotation page now says so; nothing is changed automatically,
and the report does not repeat it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import ConditionAssignment
from app.services.annotation_processor import compute_annotation, compute_annotation_from_metadata
from app.services.dataset_store import reset_all_datasets, save_table_dataset

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "proteomicscopylot" / "example_data"
SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]
PREFIX = "values ("


def _log2_upload(zero_share: float, centre: float = 22.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(4)
    values = rng.normal(centre, 2.0, (2000, len(SAMPLES)))
    values[rng.random(values.shape) < zero_share] = 0.0
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "Protein", [f"P{i}" for i in range(len(frame))])
    return frame, pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})


def _zero_warnings(result) -> list[str]:
    return [w for w in result.warnings if PREFIX in w and "are exactly 0" in w]


def _both_paths(frame, meta, is_log2=True):
    by_metadata = compute_annotation_from_metadata(frame, meta, is_log2, 1, "in at least one group")
    by_conditions = compute_annotation(
        frame, [ConditionAssignment(name=c, columns=[s for s in SAMPLES if s[0] == c]) for c in "AB"],
        is_log2, 1, "in at least one group")
    return _zero_warnings(by_metadata), _zero_warnings(by_conditions)


def test_zeros_far_below_a_log2_matrix_are_reported_in_both_annotation_paths():
    frame, meta = _log2_upload(0.15)
    zeros = int((frame[SAMPLES] == 0).to_numpy().sum())
    rows = int((frame[SAMPLES] == 0).any(axis=1).sum())
    for found in _both_paths(frame, meta):
        assert len(found) == 1
        assert found[0].startswith(f"{zeros:,} values ({zeros / frame[SAMPLES].size:.1%}) in {rows:,} rows are exactly 0")
        assert "kept as a measurement" in found[0]
        assert "export them as empty cells" in found[0]


@pytest.mark.parametrize("case", ["few zeros", "zeros near the data", "linear upload"])
def test_no_warning_when_zeros_are_rare_plausible_or_already_missing(case):
    if case == "few zeros":
        frame, meta = _log2_upload(0.003)
        is_log2 = True
    elif case == "zeros near the data":
        frame, meta = _log2_upload(0.15, centre=3.0)  # a matrix that really reaches 0
        is_log2 = True
    else:
        frame, meta = _log2_upload(0.15)
        frame[SAMPLES] = np.power(2.0, frame[SAMPLES]).where(frame[SAMPLES] != 0, 0.0)
        is_log2 = False  # a linear 0 is already read as missing
    assert _both_paths(frame, meta, is_log2) == ([], [])


@pytest.mark.parametrize("data_file,meta_file", [
    ("20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv", "protein_metadata_full.csv"),
    ("20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv", "phospho_metadata_full.csv"),
])
def test_the_bundled_example_data_raises_no_zero_warning(data_file, meta_file):
    frame = pd.read_csv(EXAMPLE / data_file, sep="\t")
    meta = pd.read_csv(EXAMPLE / meta_file)
    result = compute_annotation_from_metadata(frame, meta, True, 3, "in at least one group")
    assert _zero_warnings(result) == []


def test_the_annotation_page_receives_the_warning():
    """The route the annotation page calls returns it among the shown warnings."""
    frame, _ = _log2_upload(0.15)
    reset_all_datasets()
    save_table_dataset("zeros.tsv", "protein", frame)
    payload = {
        "kind": "protein", "isLog2Transformed": True,
        "conditions": [{"name": c, "columns": [s for s in SAMPLES if s[0] == c]} for c in "AB"],
        "filter": {"minPresent": 1},
    }
    with TestClient(app) as client:
        response = client.post("/api/annotations/generate", json=payload)
    assert response.status_code == 200, response.text[:300]
    assert any("are exactly 0" in warning for warning in response.json()["warnings"])

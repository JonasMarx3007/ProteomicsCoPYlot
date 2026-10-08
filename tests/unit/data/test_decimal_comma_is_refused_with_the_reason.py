"""A matrix whose numbers could not be read is refused with the reason.

A European export writes "1234567,8"; every value parses to missing. The
annotation used to answer "Could not reliably auto-detect ... Choose an
explicit log2 scale setting", and with an explicit scale it returned 200 with
zero rows and the locale diagnosis buried in the warnings. Both paths now
refuse up front and name the problem; a partly affected column is still only
a warning, as before.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.schemas.annotation import ConditionAssignment
from app.services.annotation_processor import compute_annotation, compute_annotation_from_metadata

SAMPLES = ["A1", "A2", "B1", "B2"]


def _comma_matrix() -> pd.DataFrame:
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2", "P3"]})
    for index, sample in enumerate(SAMPLES):
        frame[sample] = [f"{1234567 + index * 10 + row},{row + 1}" for row in range(3)]
    return frame


def _conditions() -> list[ConditionAssignment]:
    return [ConditionAssignment(name="A", columns=["A1", "A2"]), ConditionAssignment(name="B", columns=["B1", "B2"])]


@pytest.mark.parametrize("scale", [None, False, True])
def test_both_annotation_paths_refuse_and_name_the_locale(scale) -> None:
    frame = _comma_matrix()
    with pytest.raises(ValueError, match="No sample value could be read as a number.*decimal comma"):
        compute_annotation(frame, _conditions(), scale, min_present=1, filter_mode="per_group")
    metadata = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    with pytest.raises(ValueError, match="No sample value could be read as a number.*decimal comma"):
        compute_annotation_from_metadata(data=frame, metadata=metadata, is_log2_transformed=scale,
                                         min_present=1, filter_mode="per_group")


def test_a_partly_affected_column_is_still_only_a_warning() -> None:
    frame = _comma_matrix()
    frame[["A1", "A2", "B1"]] = 20.0
    frame.loc[0, "B2"] = "21.5"  # one readable value in the affected column
    computed = compute_annotation(frame, _conditions(), True, min_present=1, filter_mode="per_group")
    assert any("could not be read as numbers" in w and "B2 (2 of 3)" in w for w in computed.warnings)
    assert len(computed.filtered_data) == 3


def test_the_route_returns_the_reason_not_a_scale_question() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.dataset_store import reset_all_datasets, save_table_dataset

    reset_all_datasets()
    save_table_dataset("comma.tsv", "protein", _comma_matrix())
    try:
        with TestClient(app, base_url="http://localhost") as client:
            response = client.post("/api/annotations/generate", json={
                "kind": "protein", "isLog2Transformed": None, "minPresent": 1, "filterMode": "per_group",
                "conditions": [{"name": "A", "columns": ["A1", "A2"]}, {"name": "B", "columns": ["B1", "B2"]}],
            })
        assert response.status_code == 400, response.text
        assert "decimal comma" in response.json()["detail"]
        assert "explicit log2 scale" not in response.json()["detail"]
    finally:
        reset_all_datasets()

import pandas as pd
import pytest

from app.services.dataset_reader import sanitize_dataframe
from app.services.functions import build_metadata_from_conditions


@pytest.mark.parametrize("columns", [
    ["A", "A", "A.1"], ["A.1", "A", "A"],
    ["A", "A", "A.1", "A.2", "A.1"], ["A", "B"],
])
def test_duplicate_headers_preserve_all_values_and_original_names(columns):
    frame = pd.DataFrame([list(range(len(columns)))], columns=columns)
    result = sanitize_dataframe(frame)
    assert result.columns.is_unique
    assert set(columns) <= set(result.columns)
    assert list(result.to_dict("records")[0].values()) == list(range(len(columns)))
    assert frame.columns.tolist() == columns


@pytest.mark.parametrize("conditions", [
    [{"name": "A", "columns": ["S1"]}, {"name": "B", "columns": ["S1"]}],
    [{"name": "B", "columns": ["S1"]}, {"name": "A", "columns": ["S1"]}],
    [{"name": "A", "columns": ["S1", "S1"]}],
    [{"name": "A", "columns": ["S1", " S1 "]}],
])
def test_duplicate_sample_assignments_are_rejected(conditions):
    with pytest.raises(ValueError, match="assigned more than once"):
        build_metadata_from_conditions(pd.DataFrame({"S1": [1]}), conditions)


def test_invalid_explicit_mapping_does_not_fall_back_to_auto_detection():
    with pytest.raises(ValueError, match="No valid condition assignments"):
        build_metadata_from_conditions(pd.DataFrame({"20240131": [1]}), [
            {"name": "A", "columns": ["absent"]},
        ])


def test_valid_mapping_preserves_order_and_whitespace_resolution():
    result = build_metadata_from_conditions(pd.DataFrame({"S1": [1], " S2 ": [2]}), [
        {"name": " A ", "columns": ["S2", " S1 "]},
    ])
    assert result.metadata.to_dict("records") == [
        {"sample": " S2 ", "condition": "A"}, {"sample": "S1", "condition": "A"},
    ]
    assert not result.auto_detected


def test_empty_mapping_still_allows_automatic_sample_detection():
    result = build_metadata_from_conditions(pd.DataFrame({"20240131": [1]}), [])
    assert result.auto_detected
    assert result.metadata["sample"].tolist() == ["20240131"]

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.annotation_processor import (
    compute_annotation_from_metadata,
    detect_log2_transformed,
)
from app.services.functions import filter_data


def test_detection_uses_confirmed_samples_not_numeric_qc_columns() -> None:
    frame = pd.DataFrame(
        {
            "PG.Completeness": [100.0] * 8,
            "sample_a": np.linspace(7.5, 12.0, 8),
            "sample_b": np.linspace(8.0, 12.5, 8),
        }
    )

    detection = detect_log2_transformed(frame, ["sample_a", "sample_b"])

    assert detection.is_log2_transformed is True


def test_detection_recognizes_linear_intensities() -> None:
    frame = pd.DataFrame(
        {
            "sample_a": np.linspace(1_000, 1_000_000, 20),
            "sample_b": np.linspace(2_000, 2_000_000, 20),
        }
    )

    detection = detect_log2_transformed(frame, ["sample_a", "sample_b"])

    assert detection.is_log2_transformed is False


def test_filter_supports_count_and_percentage_across_all_scopes() -> None:
    columns = [f"s{i}" for i in range(10)]
    metadata = pd.DataFrame(
        {
            "sample": columns,
            "condition": ["a"] * 4 + ["b"] * 6,
        }
    )
    frame = pd.DataFrame(
        [
            [1, 1, 1, np.nan, 1, 1, 1, 1, np.nan, np.nan],
            [1, 1, np.nan, np.nan, 1, 1, 1, 1, np.nan, np.nan],
            [1, 1, 1, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
            [1, 1, 1, 1, 1, 1, 1, 1, np.nan, np.nan],
            [1, 1, 1, np.nan, 1, 1, 1, 1, 1, np.nan],
        ],
        columns=columns,
    )

    percentage_overall = filter_data(
        frame,
        metadata,
        min_present=0,
        mode="overall",
        method="percentage",
        min_percentage=70,
    )
    assert percentage_overall.notna().sum(axis=1).tolist() == [7, 8, 8]

    percentage_each_group = filter_data(
        frame,
        metadata,
        min_present=0,
        mode="per_group",
        method="percentage",
        min_percentage=70,
    )
    assert len(percentage_each_group) == 1
    assert percentage_each_group.notna().sum(axis=1).tolist() == [8]

    percentage_one_group = filter_data(
        frame,
        metadata,
        min_present=0,
        mode="in_at_least_one_group",
        method="percentage",
        min_percentage=70,
    )
    assert percentage_one_group.notna().sum(axis=1).tolist() == [7, 3, 8, 8]

    count_overall = filter_data(
        frame,
        metadata,
        min_present=7,
        mode="overall",
    )
    assert count_overall.notna().sum(axis=1).tolist() == [7, 8, 8]


def test_uploaded_metadata_defines_columns_for_automatic_detection() -> None:
    frame = pd.DataFrame(
        {
            "score": [500.0] * 8,
            "measurement_1": np.linspace(7.5, 12.0, 8),
            "measurement_2": np.linspace(8.0, 12.5, 8),
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": ["measurement_1", "measurement_2"],
            "condition": ["control", "treated"],
        }
    )

    computed = compute_annotation_from_metadata(
        data=frame,
        metadata=metadata,
        is_log2_transformed=None,
        min_present=0,
        filter_mode="per_group",
    )

    assert computed.is_log2_transformed is True
    assert computed.log2_auto_detected is True


def test_ambiguous_ratio_scale_requires_manual_choice() -> None:
    frame = pd.DataFrame({"sample_a": np.linspace(0.1, 1.5, 20)})
    metadata = pd.DataFrame({"sample": ["sample_a"], "condition": ["control"]})

    with pytest.raises(ValueError, match="Could not reliably auto-detect"):
        compute_annotation_from_metadata(
            data=frame,
            metadata=metadata,
            is_log2_transformed=None,
            min_present=0,
            filter_mode="per_group",
        )


def test_generate_endpoint_detects_after_condition_mapping() -> None:
    frame = pd.DataFrame(
        {
            "PG.Completeness": [100.0] * 8,
            "sample_a": np.linspace(7.5, 12.0, 8),
            "sample_b": np.linspace(8.0, 12.5, 8),
        }
    )
    csv = io.BytesIO(frame.to_csv(index=False).encode("utf-8"))

    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets/upload",
            data={"kind": "protein"},
            files={"file": ("protein.csv", csv, "text/csv")},
        )
        assert upload.status_code == 200
        assert upload.json()["suggestedIsLog2Transformed"] is None

        detected = client.post(
            "/api/annotations/log2-detect",
            json={"kind": "protein", "sampleColumns": ["sample_a", "sample_b"]},
        )
        assert detected.status_code == 200
        assert detected.json()["isLog2Transformed"] is True

        generated = client.post(
            "/api/annotations/generate",
            json={
                "kind": "protein",
                "conditions": [
                    {"name": "control", "columns": ["sample_a", "sample_b"]}
                ],
                "isLog2Transformed": None,
                "filter": {"minPresent": 0, "mode": "per_group"},
            },
        )

    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["isLog2Transformed"] is True
    assert payload["log2AutoDetected"] is True
    assert payload["filter"] == {
        "method": "at_least_n",
        "minPresent": 0,
        "minPercentage": 70.0,
        "mode": "per_group",
        "normalization": "none",
    }
    assert any("selected sample column" in warning for warning in payload["warnings"])


def test_detection_endpoint_uses_uploaded_metadata() -> None:
    frame = pd.DataFrame(
        {
            "score": [500.0] * 8,
            "measurement_1": np.linspace(7.5, 12.0, 8),
            "measurement_2": np.linspace(8.0, 12.5, 8),
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": ["measurement_1", "measurement_2"],
            "condition": ["control", "treated"],
        }
    )

    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets/upload",
            data={"kind": "protein"},
            files={
                "file": (
                    "protein.csv",
                    io.BytesIO(frame.to_csv(index=False).encode("utf-8")),
                    "text/csv",
                )
            },
        )
        assert upload.status_code == 200

        metadata_upload = client.post(
            "/api/annotations/metadata/upload",
            data={"kind": "protein"},
            files={
                "file": (
                    "metadata.csv",
                    io.BytesIO(metadata.to_csv(index=False).encode("utf-8")),
                    "text/csv",
                )
            },
        )
        assert metadata_upload.status_code == 200

        detected = client.post(
            "/api/annotations/log2-detect",
            json={"kind": "protein", "sampleColumns": []},
        )

    assert detected.status_code == 200
    assert detected.json()["isLog2Transformed"] is True
    assert detected.json()["sampleCount"] == 2


def _linear(columns: list[str], rows: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({column: rng.lognormal(13, 1.5, rows) for column in columns})


def _log2(columns: list[str], rows: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    return pd.DataFrame({column: rng.normal(22, 2, rows) for column in columns})


@pytest.mark.parametrize(
    "odd_column",
    [
        "log2_s4",
        "run_log2024_05",
        "Log2FC_ref",
    ],
)
def test_one_log2_named_column_does_not_decide_for_the_dataset(odd_column: str) -> None:
    columns = ["s1", "s2", "s3", odd_column]
    detection = detect_log2_transformed(_linear(columns), columns)
    assert detection.is_log2_transformed is False, detection.reason


def test_a_date_in_a_run_name_is_not_a_scale_marker() -> None:
    columns = ["run_log2024_01", "run_log2024_02", "run_log2024_03"]
    detection = detect_log2_transformed(_linear(columns), columns)
    assert detection.is_log2_transformed is False, detection.reason


def test_consistent_log2_names_are_trusted_when_the_values_agree() -> None:
    columns = ["log2_s1", "log2_s2", "log2_s3"]
    detection = detect_log2_transformed(_log2(columns), columns)
    assert detection.is_log2_transformed is True
    assert "column names" in detection.reason


def test_names_and_values_in_conflict_refuse_to_guess() -> None:
    columns = ["log2_s1", "log2_s2", "log2_s3", "log2_s4"]
    detection = detect_log2_transformed(_linear(columns), columns)
    assert detection.is_log2_transformed is None
    assert "linear-intensity scale" in detection.reason


def test_the_conflict_is_reported_as_an_actionable_error() -> None:
    from app.services.annotation_processor import resolve_log2_state

    columns = ["log2_s1", "log2_s2"]
    with pytest.raises(ValueError, match="Choose an explicit log2 scale setting"):
        resolve_log2_state(_linear(columns), columns, None)


def test_an_explicit_choice_still_overrides_the_conflict() -> None:
    from app.services.annotation_processor import resolve_log2_state

    columns = ["log2_s1", "log2_s2"]
    resolved, auto_detected, warning = resolve_log2_state(_linear(columns), columns, False)
    assert resolved is False
    assert auto_detected is False
    assert warning is None


def test_unnamed_log2_values_are_still_detected_from_the_values_alone() -> None:
    columns = ["s1", "s2", "s3"]
    assert detect_log2_transformed(_log2(columns), columns).is_log2_transformed is True


def _twelve_sample_dataset() -> tuple[pd.DataFrame, list[str]]:
    columns = [f"S{i}" for i in range(1, 13)]
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {"ProteinNames": [f"P{i}" for i in range(50)],
         **{c: rng.normal(22, 1, 50) for c in columns}}
    )
    return frame, columns


def _annotate(frame: pd.DataFrame, metadata: pd.DataFrame):
    from app.services.annotation_processor import compute_annotation_from_metadata

    return compute_annotation_from_metadata(
        data=frame, metadata=metadata, is_log2_transformed=True,
        min_present=1, filter_mode="per_group",
    )


def test_a_clean_metadata_match_produces_no_mismatch_warning() -> None:
    frame, columns = _twelve_sample_dataset()
    metadata = pd.DataFrame({"sample": columns, "condition": ["A"] * 6 + ["B"] * 6})
    result = _annotate(frame, metadata)
    assert len(result.metadata) == 12
    assert not [w for w in result.warnings if "not a column" in w]


def test_mistyped_sample_names_are_reported_with_the_annotated_count() -> None:
    frame, columns = _twelve_sample_dataset()
    metadata = pd.DataFrame({"sample": columns, "condition": ["A"] * 6 + ["B"] * 6})
    metadata.loc[[6, 7, 8], "sample"] = ["s7", "s8", "s9"]

    result = _annotate(frame, metadata)

    assert len(result.metadata) == 9
    assert result.metadata["condition"].value_counts().to_dict() == {"A": 6, "B": 3}

    reported = [w for w in result.warnings if "not a column" in w]
    assert reported, result.warnings
    assert "s7" in reported[0] and "s8" in reported[0] and "s9" in reported[0]
    assert "9 sample(s) were annotated" in reported[0]


def test_a_shared_metadata_file_covering_extra_runs_still_annotates_everything() -> None:
    frame, columns = _twelve_sample_dataset()
    metadata = pd.DataFrame(
        {"sample": columns + ["S98", "S99"], "condition": ["A"] * 6 + ["B"] * 6 + ["C", "C"]}
    )
    result = _annotate(frame, metadata)
    assert len(result.metadata) == 12
    assert result.metadata["condition"].value_counts().to_dict() == {"A": 6, "B": 6}
    assert [w for w in result.warnings if "not a column" in w]


def _numeric_text_dataset() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    columns = [f"S{i}" for i in range(1, 7)]
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {"ProteinNames": [f"P{i}" for i in range(200)],
         **{c: [f"{v:.3f}" for v in rng.normal(22, 1, 200)] for c in columns}}
    )
    metadata = pd.DataFrame({"sample": columns, "condition": ["A"] * 3 + ["B"] * 3})
    return frame, metadata, columns


def _unreadable_warning(result) -> list[str]:
    return [w for w in result.warnings if "could not be read as numbers" in w]


def test_clean_numeric_text_produces_no_warning() -> None:
    frame, metadata, _ = _numeric_text_dataset()
    assert not _unreadable_warning(_annotate(frame, metadata))


def test_a_decimal_comma_column_is_reported_not_silently_missing() -> None:
    frame, metadata, _ = _numeric_text_dataset()
    frame["S4"] = [v.replace(".", ",") for v in frame["S4"]]

    result = _annotate(frame, metadata)

    reported = _unreadable_warning(result)
    assert reported, result.warnings
    assert "S4" in reported[0]
    assert "200" in reported[0], "the count of lost values must be stated"


def test_documented_placeholders_are_not_reported_as_unreadable() -> None:
    frame, metadata, _ = _numeric_text_dataset()
    frame.loc[:99, "S2"] = "N/A"
    assert not _unreadable_warning(_annotate(frame, metadata))


@pytest.mark.parametrize("placeholder", ["NA", "n/a", "-", "", "Filtered", "#DIV/0!", "null"])
def test_every_recognised_placeholder_stays_quiet(placeholder: str) -> None:
    frame, metadata, _ = _numeric_text_dataset()
    frame.loc[:149, "S3"] = placeholder
    assert not _unreadable_warning(_annotate(frame, metadata)), placeholder


def test_below_detection_markers_are_reported() -> None:
    frame, metadata, _ = _numeric_text_dataset()
    frame.loc[:59, "S5"] = "<0.01"
    reported = _unreadable_warning(_annotate(frame, metadata))
    assert reported and "S5" in reported[0]


def test_an_already_numeric_frame_is_not_scanned() -> None:
    columns = [f"S{i}" for i in range(1, 7)]
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(
        {"ProteinNames": [f"P{i}" for i in range(50)],
         **{c: rng.normal(22, 1, 50) for c in columns}}
    )
    metadata = pd.DataFrame({"sample": columns, "condition": ["A"] * 3 + ["B"] * 3})
    assert not _unreadable_warning(_annotate(frame, metadata))


def _two_sample_frame() -> pd.DataFrame:
    return pd.DataFrame({"ProteinNames": ["P1"], "S1": [1.0], "S2": [2.0]})


def test_a_sample_repeated_identically_is_reported_not_collapsed() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    metadata = pd.DataFrame(
        {"sample": ["S1", "S1", "S2"], "condition": ["A", "A", "B"]}
    )
    with pytest.raises(ValueError, match="more than once") as excinfo:
        normalize_uploaded_metadata(_two_sample_frame(), metadata)
    assert "S1" in str(excinfo.value), "the repeated sample must be named"


def test_metadata_with_each_sample_once_is_accepted() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    metadata = pd.DataFrame({"sample": ["S1", "S2"], "condition": ["A", "B"]})
    result = normalize_uploaded_metadata(_two_sample_frame(), metadata)
    assert list(zip(result["sample"], result["condition"])) == [("S1", "A"), ("S2", "B")]


def test_a_sample_assigned_two_conditions_is_rejected() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    metadata = pd.DataFrame(
        {"sample": ["S1", "S1", "S2"], "condition": ["A", "B", "B"]}
    )
    with pytest.raises(ValueError, match="more than one value") as excinfo:
        normalize_uploaded_metadata(_two_sample_frame(), metadata)
    message = str(excinfo.value)
    assert "S1" in message, "the offending sample must be named"
    assert "A" in message and "B" in message, "both conflicting values must be shown"


def test_a_conflict_in_any_column_is_rejected_not_just_condition() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    metadata = pd.DataFrame(
        {"sample": ["S1", "S1", "S2"], "condition": ["A", "A", "B"], "batch": ["1", "2", "1"]}
    )
    with pytest.raises(ValueError, match="more than one value"):
        normalize_uploaded_metadata(_two_sample_frame(), metadata)


def test_row_order_no_longer_decides_the_answer() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    forward = pd.DataFrame({"sample": ["S1", "S1", "S2"], "condition": ["A", "B", "B"]})
    reversed_ = forward.iloc[::-1].reset_index(drop=True)

    for metadata in (forward, reversed_):
        with pytest.raises(ValueError, match="more than one value"):
            normalize_uploaded_metadata(_two_sample_frame(), metadata)


def test_the_pair_id_path_still_reports_its_own_message() -> None:
    from app.services.annotation_processor import normalize_uploaded_metadata

    metadata = pd.DataFrame(
        {"sample": ["S1", "S1", "S2"], "condition": ["A", "B", "B"], "pair_id": ["1", "2", "1"]}
    )
    with pytest.raises(ValueError, match="pair_id must contain each sample exactly once"):
        normalize_uploaded_metadata(_two_sample_frame(), metadata)

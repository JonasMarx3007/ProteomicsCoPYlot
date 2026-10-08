import pandas as pd
import pytest
import numpy as np
import io

from app.services.dataset_reader import sanitize_dataframe
from app.services.functions import build_metadata_from_conditions


@pytest.mark.parametrize("vendor", ["diann", "spectronaut"])
@pytest.mark.parametrize("extension", ["tsv", "parquet"])
def test_export_matrix_missingness_and_run_identity(vendor, extension):
    from app.services.dataset_reader import read_dataframe
    from app.services.annotation_processor import compute_annotation_from_metadata
    from proteomicscopylot import notebook_functions as notebook
    identifiers = ("Protein.Ids", "Genes") if vendor == "diann" else ("PG.ProteinGroups", "PG.Genes")
    samples = [r"C:\batch1\sample.d", r"C:\batch2\sample.d", "sample 3.PG.Quantity", "empty_run"]
    raw = pd.DataFrame({identifiers[0]: ["P1;P2", "P3", "P4", "P5"],
                        identifiers[1]: ["GENE_A;GENE_B", "G3", "G4", "G5"],
                        samples[0]: [1., 0., 1.2e8, np.nan],
                        samples[1]: [2., np.nan, 1.2e8, np.nan],
                        samples[2]: [4., 8., 1.2e8, np.nan],
                        samples[3]: [np.nan]*4})
    stream = io.BytesIO()
    if extension == "tsv":
        stream.write(raw.to_csv(sep="\t", index=False).encode("utf-8-sig"))
    else:
        raw.to_parquet(stream, index=False)
    stream.seek(0)
    loaded = read_dataframe(f"matrix.{extension}", stream)
    meta = pd.DataFrame({"sample": samples, "condition": ["A", "A", "B", "B"]}).iloc[::-1]
    result = compute_annotation_from_metadata(loaded, meta, False, 1, "overall")
    expected = notebook.log2_transform_data(loaded, meta)
    np.testing.assert_allclose(result.log2_data[samples], expected[samples], equal_nan=True)
    assert result.log2_data.loc[0, samples[0]] == 0
    assert np.isnan(result.log2_data.loc[1, samples[0]])
    assert result.log2_data[samples[3]].isna().all()
    assert result.metadata["sample"].tolist() == meta["sample"].tolist()
    assert result.filtered_data.ProteinNames.tolist() == ["P1;P2", "P3", "P4"]
    assert result.filtered_data.GeneNames.iloc[0] == "GENE_A;GENE_B"


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


def test_auto_detection_skips_per_run_statistics():
    from app.services.functions import _auto_sample_columns

    spectronaut = ["PG.ProteinGroups", "[1] 20240131_A1.raw.PG.Quantity", "[1] 20240131_A1.raw.PG.Qvalue",
                   "[1] 20240131_A1.raw.PG.NrOfStrippedSequencesIdentified", "[2] 20240131_B1.raw.PG.Quantity"]
    assert _auto_sample_columns(spectronaut) == ["[1] 20240131_A1.raw.PG.Quantity", "[2] 20240131_B1.raw.PG.Quantity"]
    plain = ["Protein", "20240131_A1", "20240131_A1_Qvalue", "20240131_A1 count", "20240131_B1"]
    assert _auto_sample_columns(plain) == ["20240131_A1", "20240131_B1"]


@pytest.mark.parametrize("run_name", ["LFQ", "intensity", "abundance", "area"])
def test_auto_detection_uses_measurement_suffix_not_run_name(run_name):
    run = f"[1] 20241018_{run_name}_run.raw.PG."
    quantity = run + "Quantity"
    statistics = [run + suffix for suffix in ("Qvalue", "NrOfPrecursors", "Score", "PEP")]
    result = build_metadata_from_conditions(pd.DataFrame({
        column: [1.0] for column in [quantity, *statistics]
    }), [])
    assert result.auto_detected
    assert result.metadata["sample"].tolist() == [quantity]
    with pytest.raises(ValueError, match="no auto-detectable sample"):
        build_metadata_from_conditions(pd.DataFrame({column: [1.0] for column in statistics}), [])


def test_auto_detection_keeps_plain_diann_run_names_with_measurement_words():
    samples = ["20241018_LFQ_A.raw", "20241018_score_B.raw", "20241018_count_C.raw"]
    result = build_metadata_from_conditions(pd.DataFrame({sample: [1.0] for sample in samples}), [])
    assert result.metadata["sample"].tolist() == samples


@pytest.mark.parametrize("suffix", ["Quantity", "Log2Quantity", "NormalizedQuantity", "Intensity", "Abundance", "Area", "LFQ"])
def test_auto_detection_keeps_quantity_fields(suffix):
    from app.services.functions import _auto_sample_columns

    sample = f"[1] 20241018_score_run.raw.PG.{suffix}"
    assert _auto_sample_columns([sample, "[1] 20241018_score_run.raw.PG.Qvalue"]) == [sample]


def test_explicit_sample_mapping_does_not_use_auto_detection_heuristics():
    sample = "20241018_Qvalue"
    result = build_metadata_from_conditions(pd.DataFrame({sample: [1.0]}), [
        {"name": "A", "columns": [sample]},
    ])
    assert not result.auto_detected
    assert result.metadata.to_dict("records") == [{"sample": sample, "condition": "A"}]


def test_auto_annotation_transforms_and_filters_only_measurements():
    from app.services.annotation_processor import compute_annotation

    sample = "[1] 20241018_LFQ_run.raw.PG.Quantity"
    qvalue = "[1] 20241018_LFQ_run.raw.PG.Qvalue"
    counts = "[1] 20241018_LFQ_run.raw.PG.NrOfPrecursors"
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2"], sample: [8., 0.],
                          qvalue: [0.01, 0.02], counts: [3, 4]})
    result = compute_annotation(frame, [], False, 1, "overall")
    assert result.metadata["sample"].tolist() == [sample]
    assert result.log2_data[sample].iloc[0] == 3.0
    assert pd.isna(result.log2_data[sample].iloc[1])
    pd.testing.assert_frame_equal(result.log2_data[[qvalue, counts]], frame[[qvalue, counts]])
    assert result.filtered_data["ProteinNames"].tolist() == ["P1"]

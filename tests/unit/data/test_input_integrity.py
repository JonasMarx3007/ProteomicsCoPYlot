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

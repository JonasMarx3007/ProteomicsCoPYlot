"""Excluded phosphosites must never re-enter through protein aggregation."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services import annotation_store, dataset_store, phosprot_tools
from app.services.functions import filter_data


@pytest.fixture(params=["at_least_n", "percentage"])
def rejected_sites(request):
    annotation_store.reset_all_annotations()
    dataset_store.reset_all_datasets()
    # Neither site has two observations in either group. Collapsing the
    # complementary observations first can nevertheless produce a complete row.
    frame = pd.DataFrame({
        "UPD_seq": ["SEQ1", "SEQ2"], "PTM_localization": ["S1", "S2"],
        "Protein_group": ["P1", "P1"], "Gene_group": ["G1", "G1"],
        "PTM_Collapse_key": ["K1", "K2"],
        "a1": [10., np.nan], "a2": [np.nan, 11.],
        "b1": [12., np.nan], "b2": [np.nan, 13.],
    })
    metadata = pd.DataFrame({"sample": ["a1", "a2", "b1", "b2"], "condition": ["A", "A", "B", "B"]})
    filtered = filter_data(frame, metadata, min_present=2, mode="per_group",
                           method=request.param, min_percentage=100)
    assert filtered.empty and len(filtered.columns) > 0
    stored = annotation_store.save_annotation(
        kind="phospho", source_data=frame, metadata=metadata, log2_data=frame,
        filtered_data=filtered, is_log2_transformed=True, metadata_source="manual",
        filter_config=AnnotationFilterConfig(minPresent=2, mode="per_group",
                                             method=request.param, minPercentage=100),
        auto_detected=False, warnings=[],
    )
    dataset_store.save_table_dataset("sites.csv", "phospho", frame)
    try:
        yield stored
    finally:
        annotation_store.reset_all_annotations()
        dataset_store.reset_all_datasets()


@pytest.mark.parametrize("mode", ["robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na"])
@pytest.mark.parametrize("source", ["non_imputed", "imputed"])
def test_aggregation_rejects_completed_empty_filter(rejected_sites, mode, source):
    with pytest.raises(ValueError, match="No features passed the selected filter"):
        phosprot_tools.aggregate_from_phospho(mode, source=source)
    assert annotation_store.get_annotation("phosprot") is None
    assert annotation_store.get_annotation("phospho") is rejected_sites


@pytest.mark.parametrize("source", ["non_imputed", "imputed"])
def test_empty_filter_blocks_before_aggregation_or_imputed_lookup(rejected_sites, monkeypatch, source):
    def forbidden(*args, **kwargs):
        pytest.fail("Rejected sites must not reach aggregation or imputed-source lookup")
    monkeypatch.setattr(phosprot_tools, "transform_phosprot", forbidden)
    # The imputed matrix is read before the collapse applies its own localization cutoff.
    monkeypatch.setattr(phosprot_tools, "_select_matrix_all_rows", forbidden)
    with pytest.raises(ValueError, match="No features passed the selected filter"):
        phosprot_tools.aggregate_from_phospho("mean", source=source)


@pytest.mark.parametrize("missing", [None, pd.DataFrame()])
def test_absent_filter_still_allows_log2_source(rejected_sites, missing):
    rejected_sites.filtered_data = missing
    # The log2 source is used: the protein is built from its two sites. Neither
    # site is quantified in every sample, so under the shared-site rule the sum
    # has no value and the protein row stays missing rather than being assembled
    # from complementary observations.
    result = phosprot_tools.aggregate_from_phospho("sum_ignore_na")
    assert len(result.source_data) == 1 and result.source_data.loc[0, "site_num"] == 2
    assert result.source_data.loc[0, ["a1", "a2", "b1", "b2"]].isna().all()
    assert len(result.filtered_data) == 0


def test_nonempty_filter_excludes_rejected_sites(rejected_sites):
    included = rejected_sites.log2_data.iloc[[0]].copy()
    included[["a1", "a2", "b1", "b2"]] = [[10., 11., 12., 13.]]
    rejected_sites.filtered_data = included
    result = phosprot_tools.aggregate_from_phospho("mean")
    assert result.source_data.loc[0, "site_num"] == 1
    assert result.source_data.loc[0, ["a1", "a2", "b1", "b2"]].to_numpy(dtype=float) == pytest.approx([10., 11., 12., 13.])


@pytest.mark.parametrize("source", ["non_imputed", "imputed"])
def test_ui_aggregation_api_preserves_existing_output_on_rejection(rejected_sites, source):
    previous = rejected_sites.log2_data.iloc[[0]].copy()
    existing_dataset = dataset_store.save_table_dataset("previous.csv", "phosprot", previous)
    existing_annotation = annotation_store.save_annotation(
        kind="phosprot", source_data=previous, metadata=rejected_sites.metadata,
        log2_data=previous, filtered_data=previous, is_log2_transformed=True,
        metadata_source="manual", filter_config=AnnotationFilterConfig(),
        auto_detected=False, warnings=[], phosprot_aggregation="mean",
    )
    with TestClient(app) as client:
        response = client.post("/api/annotations/phosprot/aggregate", json={"mode": "robust_site_median", "source": source})
    assert response.status_code == 400, response.text
    assert "No features passed the selected filter" in response.json()["detail"]
    assert "Unfiltered data has not been substituted" in response.json()["detail"]
    assert annotation_store.get_annotation("phosprot") is existing_annotation
    assert dataset_store.get_current_dataset("phosprot") is existing_dataset

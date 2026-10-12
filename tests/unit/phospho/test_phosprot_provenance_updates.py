"""Aggregation provenance is invariant under unrelated annotation updates."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


from app.schemas.annotation import AnnotationFilterConfig, SamplePairAssignment
from app.main import app
from app.schemas.data_tools import ImputationRunRequest
from app.services import annotation_store, data_tools, phosprot_tools, plot_images, restore_state
from app.services.dataset_store import reset_all_datasets, save_table_dataset
from app.services.analysis_matrix import phosprot_values_are_centred
from app.services.metadata_upload_store import reset_all_uploaded_metadata
from app.services.dataset_store import get_current_dataset
from app.services.metadata_upload_store import create_profile, set_active_profile
from app.api.routes_annotations import generate_annotation
from app.schemas.annotation import AnnotationGenerateRequest


@pytest.fixture(autouse=True)
def isolated_stores():
    def reset():
        annotation_store.reset_all_annotations()
        reset_all_datasets()
        reset_all_uploaded_metadata()
    reset()
    try:
        yield
    finally:
        reset()


@pytest.mark.parametrize("mode", ["robust_site_median", "sum_ignore_na", "sum_propagate_na", "mean", "uploaded", None])
@pytest.mark.parametrize("source", ["non_imputed", "imputed"])
def test_aggregation_update_plot_restore(tmp_path, monkeypatch, mode, source):
    samples = ["a1", "a2", "b1", "b2"]
    metadata = pd.DataFrame({"sample": samples, "condition": ["A", "A", "B", "B"]})
    sites = pd.DataFrame({
        "UPD_seq": [f"SEQ{i}" for i in range(6)],
        "PTM_localization": ["S1"] * 6,
        "Protein_group": ["P1", "P1", "P2", "P2", "P3", "P3"],
        "Gene_group": ["G1", "G1", "G2", "G2", "G3", "G3"],
        "PTM_Collapse_key": [f"K{i}" for i in range(6)],
        "a1": [np.nan, np.nan, 12., 13., 16., 18.],
        "a2": [10., 11., 13., 15., 17., 20.],
        "b1": [12., 14., 15., 18., 21., 22.],
        "b2": [13., 15., 17., 19., 22., 24.],
    })
    annotation_store.save_annotation(
        kind="phospho", source_data=sites, metadata=metadata, log2_data=sites,
        filtered_data=sites, is_log2_transformed=True, metadata_source="manual",
        filter_config=AnnotationFilterConfig(minPresent=0), auto_detected=False, warnings=[],
    )
    save_table_dataset("sites.csv", "phospho", sites)
    if source == "imputed":
        result = data_tools.run_imputation(ImputationRunRequest(kind="phospho"))
        assert result.missingBefore == 2
        assert result.missingAfter == 0
        imputed = annotation_store.get_annotation("phospho").imputed_data
        observed = sites[samples].notna()
        pd.testing.assert_frame_equal(sites[samples].where(observed), imputed[samples].where(observed))
    original = phosprot_tools.aggregate_from_phospho(
        mode if mode not in (None, "uploaded") else "mean", source=source
    )
    expected_aggregate = phosprot_tools.transform_phosprot(
        annotation_store.get_annotation("phospho").imputed_data if source == "imputed" else sites,
        metadata, mode=mode if mode not in (None, "uploaded") else "mean",
        data_scale="log2", coverage_data=sites,
    )
    pd.testing.assert_frame_equal(original.source_data, expected_aggregate)
    expected_aggregate = phosprot_tools.transform_phosprot(
        annotation_store.get_annotation("phospho").imputed_data if source == "imputed" else sites,
        metadata, mode=mode if mode not in (None, "uploaded") else "mean",
        data_scale="log2", coverage_data=sites,
    )
    pd.testing.assert_frame_equal(original.source_data, expected_aggregate)
    # Uploaded/legacy annotations have no inferred aggregation provenance.
    original.phosprot_aggregation = mode
    frame = original.source_data.copy(deep=True)
    path = tmp_path / "phosprot.csv"
    frame.to_csv(path, index=False)
    save_table_dataset(path.name, "phosprot", frame, source_path=path, phosprot_aggregation=mode)
    sites_path = tmp_path / "sites.csv"
    sites.to_csv(sites_path, index=False)
    save_table_dataset(sites_path.name, "phospho", sites, source_path=sites_path)
    monkeypatch.setattr(plot_images, "_plotly_html", lambda figure: figure)

    def check_interpretation():
        current = annotation_store.get_annotation("phosprot")
        assert current.phosprot_aggregation == mode
        assert phosprot_values_are_centred("phosprot") == (mode == "robust_site_median")
        figure = plot_images.qc_abundance_interactive_html("phosprot")
        assert ("Ratio to Site Median" in figure.layout.yaxis.title.text) == (mode == "robust_site_median")
        return current

    check_interpretation()
    request = AnnotationGenerateRequest(
        kind="phosprot", isLog2Transformed=True,
        conditions=[{"name": "A", "columns": samples[:2]}, {"name": "B", "columns": samples[2:]}],
        filter=AnnotationFilterConfig(minPresent=0),
    )
    generate_annotation(request)
    check_interpretation()
    for operation in ("blocked_impute", "pair"):
        before = annotation_store.get_annotation("phosprot")
        if operation == "blocked_impute":
            with pytest.raises(ValueError, match="Direct phosphoprotein imputation is disabled"):
                data_tools.run_imputation(ImputationRunRequest(kind="phosprot"))
        else:
            annotation_store.update_annotation_pairing("phosprot", "A", "B", [
                SamplePairAssignment(condition1Sample="a1", condition2Sample="b1"),
                SamplePairAssignment(condition1Sample="a2", condition2Sample="b2"),
            ])
        after = check_interpretation()
        for field in ("source_data", "log2_data", "filtered_data"):
            pd.testing.assert_frame_equal(getattr(before, field), getattr(after, field))
        pd.testing.assert_frame_equal(before.imputed_data, after.imputed_data)
        assert after.imputation is None
        if operation == "blocked_impute":
            pd.testing.assert_frame_equal(before.metadata, after.metadata)
        else:
            paired = after.metadata.set_index("sample")["pair_id"]
            assert paired["a1"] == paired["b1"]
            assert paired["a2"] == paired["b2"]
            assert paired["a1"] != paired["a2"]

    expected = annotation_store.get_annotation("phosprot")
    state = restore_state.decode_restore_blob(restore_state.export_state_blob())
    annotation_store.reset_all_annotations()
    reset_all_datasets()
    restore_state.apply_restore_state(state, {})
    restored = check_interpretation()
    assert get_current_dataset("phosprot").phosprot_aggregation == mode
    pd.testing.assert_frame_equal(restored.filtered_data[samples], expected.filtered_data[samples])
    assert restored.imputed_data.empty
    pd.testing.assert_frame_equal(restored.metadata, expected.metadata)
    generate_annotation(request)
    check_interpretation()


def _seed_phosprot_upload():
    frame = pd.DataFrame({"Protein_group": ["P1"], "A": [10.], "B": [12.]})
    annotation_store.save_annotation(
        kind="phospho", source_data=frame, log2_data=frame, filtered_data=frame,
        metadata=pd.DataFrame({"sample": ["A", "B"], "condition": ["A", "B"]}),
        is_log2_transformed=True, metadata_source="manual", filter_config=AnnotationFilterConfig(minPresent=0),
        auto_detected=False, warnings=[],
    )
    phosprot_tools.upload_phosprot(frame, "valid.csv", True)
    return frame


@pytest.mark.parametrize("failure", ["samples", "scale", "filter"])
def test_rejected_upload_preserves_dataset_and_all_profile_annotations(monkeypatch, failure):
    frame = _seed_phosprot_upload()
    before_dataset = get_current_dataset("phosprot")
    before_annotation = annotation_store.get_annotation("phosprot")
    annotation_store.store_prepared_annotation(before_annotation, metadata_profile_name="other")

    def fail(*args, **kwargs):
        raise ValueError("Synthetic validation failure")

    if failure == "samples":
        frame = frame.rename(columns={"A": "unknownA", "B": "unknownB"})
    else:
        monkeypatch.setattr(phosprot_tools, "resolve_log2_state" if failure == "scale" else "filter_data", fail)
    with pytest.raises(ValueError):
        phosprot_tools.upload_phosprot(frame, "rejected.csv", True)
    assert get_current_dataset("phosprot") is before_dataset
    assert annotation_store.get_annotation("phosprot") is before_annotation
    assert annotation_store.get_annotation("phosprot", metadata_profile_name="other") is before_annotation


def test_successful_replacement_clears_stale_profiles_and_replaces_provenance():
    frame = _seed_phosprot_upload()
    previous = annotation_store.get_annotation("phosprot")
    previous.phosprot_aggregation = "robust_site_median"
    annotation_store.store_prepared_annotation(previous, metadata_profile_name="other")
    replacement = frame.assign(A=20.)
    current = phosprot_tools.upload_phosprot(replacement, "replacement.csv", True)
    assert get_current_dataset("phosprot").filename == "replacement.csv"
    assert get_current_dataset("phosprot").phosprot_aggregation == "uploaded"
    assert current.phosprot_aggregation == "uploaded"
    pd.testing.assert_frame_equal(current.source_data, replacement)
    assert annotation_store.get_annotation("phosprot", metadata_profile_name="other") is None


def test_rejected_aggregation_preserves_current_dataset(monkeypatch):
    frame = _seed_phosprot_upload()
    previous_dataset = get_current_dataset("phosprot")
    previous_annotation = annotation_store.get_annotation("phosprot")
    monkeypatch.setattr(phosprot_tools, "transform_phosprot", lambda *args, **kwargs: frame.copy())

    def fail(*args, **kwargs):
        raise ValueError("Synthetic filter failure")

    monkeypatch.setattr(phosprot_tools, "filter_data", fail)
    with pytest.raises(ValueError, match="filter failure"):
        phosprot_tools.aggregate_from_phospho("mean")
    assert get_current_dataset("phosprot") is previous_dataset
    assert annotation_store.get_annotation("phosprot") is previous_annotation


def test_reannotation_in_new_profile_uses_dataset_provenance():
    _seed_phosprot_upload()
    get_current_dataset("phosprot").phosprot_aggregation = "robust_site_median"
    create_profile("other")
    set_active_profile("other")
    generate_annotation(AnnotationGenerateRequest(
        kind="phosprot", isLog2Transformed=True,
        conditions=[{"name": "A", "columns": ["A"]}, {"name": "B", "columns": ["B"]}],
        filter=AnnotationFilterConfig(minPresent=0),
    ))
    assert annotation_store.get_annotation("phosprot").phosprot_aggregation == "robust_site_median"


@pytest.mark.parametrize("method", ["quantile", "numerical"])
@pytest.mark.parametrize("endpoint", ["run", "download"])
def test_direct_phosprot_imputation_api_is_disabled(method, endpoint, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No imputation calculation may run for phosphoproteins")
    monkeypatch.setattr(data_tools, "impute_values_with_diagnostics", forbidden)
    with TestClient(app) as client:
        response = client.post(f"/api/data-tools/imputation/{endpoint}", json={"kind": "phosprot", "method": method})
    assert response.status_code == 400, response.text
    assert "Impute phosphosite data first" in response.json()["detail"]
    assert annotation_store.get_annotation("phosprot") is None


@pytest.mark.parametrize("plot", ["before-missing", "overall-fit", "after-imputation"])
def test_direct_phosprot_imputation_plots_are_disabled(plot, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No imputation calculation may run for phosphoproteins")
    monkeypatch.setattr(plot_images, "impute_values_with_diagnostics", forbidden)
    with TestClient(app) as client:
        response = client.get(f"/api/plots/imputation/phosprot/{plot}.png")
    assert response.status_code == 400, response.text
    assert "Impute phosphosite data first" in response.json()["detail"]

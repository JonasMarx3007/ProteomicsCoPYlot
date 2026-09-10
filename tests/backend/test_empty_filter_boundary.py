from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig
from app.services import annotation_store, data_tools, dataset_store, functions
from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.r_runtime import detect_r_runtime
from proteomicscopylot import notebook_functions


@pytest.fixture(params=["protein", "phospho", "phosprot"])
def empty_filtered(request, tmp_path):
    annotation_store.reset_all_annotations()
    dataset_store.reset_all_datasets()
    kind = request.param
    samples = [f"{condition}{i}" for condition in "ABCD" for i in range(3)]
    frame = pd.DataFrame({
        sample: [np.nan, np.nan] if sample.endswith("2") else [10. + i, 20. + i]
        for i, sample in enumerate(samples)
    })
    for label in ("ProteinNames", "GeneNames", "PTM_Collapse_key", "Protein_group", "Gene_group"):
        frame[label] = ["P1", "P2"]
    meta = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    computed = compute_annotation_from_metadata(
        data=frame, metadata=meta, is_log2_transformed=True,
        min_present=3, filter_mode="per_group",
    )
    assert computed.filtered_data.empty
    assert set(samples).issubset(computed.filtered_data.columns)
    dataset_store.save_table_dataset(kind=kind, filename=str(tmp_path / "fixture.tsv"), frame=frame)
    annotation_store.save_annotation(
        kind=kind, source_data=frame, metadata=computed.metadata,
        log2_data=computed.log2_data, filtered_data=computed.filtered_data,
        is_log2_transformed=True, metadata_source="uploaded",
        filter_config=AnnotationFilterConfig(minPresent=3), auto_detected=False, warnings=[],
    )
    try:
        yield kind, frame, meta
    finally:
        annotation_store.reset_all_annotations()
        dataset_store.reset_all_datasets()


@pytest.mark.parametrize("source", ["auto", "data", "filtered"])
def test_completed_empty_filter_never_falls_back(empty_filtered, source):
    kind, _, _ = empty_filtered
    with pytest.raises(ValueError, match="No features passed the selected filter"):
        functions.analysis_data_source(kind, source)


def test_explicit_unfiltered_lookup_still_works(empty_filtered):
    kind, frame, _ = empty_filtered
    source, selected, _, _ = functions.analysis_data_source(kind, "log2")
    assert source == "log2"
    assert len(selected) == len(frame) == 2
    assert annotation_store.get_annotation(kind).filtered_data.empty


@pytest.mark.parametrize("endpoint", [
    "/api/stats/volcano/run", "/api/stats/volcano-control/run",
    "/api/stats/anova/run", "/api/stats/ora/run", "/api/stats/simulation/run",
    "/api/data-tools/imputation/run", "/api/data-tools/imputation/download",
])
def test_ui_api_consumers_report_no_data_without_substitution(empty_filtered, endpoint):
    kind, _, _ = empty_filtered
    payload = {"kind": kind, "condition1": "A", "condition2": "B"}
    if "volcano-control" in endpoint:
        payload.update(condition1Control="C", condition2Control="D")
    with TestClient(app) as client:
        response = client.post(endpoint, json=payload)
    assert response.status_code == 400, response.text
    if kind == "phospho" and endpoint == "/api/stats/ora/run":
        # This combination is rejected before source selection, independently
        # of filtering. Do not expand the supported scientific workflows.
        assert "Phospho (site-level) is not supported" in response.json()["detail"]
    elif kind == "phosprot" and "/imputation/" in endpoint:
        assert "Direct phosphoprotein imputation is disabled" in response.json()["detail"]
    else:
        assert "No features passed the selected filter" in response.json()["detail"]
        assert "Unfiltered data has not been substituted" in response.json()["detail"]
    annotation = annotation_store.get_annotation(kind)
    assert annotation.filtered_data.empty
    assert annotation.imputation is None
    assert annotation.imputed_data.empty


def test_imputation_fails_before_drawing_values(empty_filtered, monkeypatch):
    kind, _, _ = empty_filtered
    def unexpected(*args, **kwargs):
        pytest.fail("Imputation must not run on excluded rows")
    monkeypatch.setattr(data_tools, "impute_values_with_diagnostics", unexpected)
    from app.schemas.data_tools import ImputationRunRequest
    message = "Direct phosphoprotein imputation is disabled" if kind == "phosprot" else "No features passed"
    with pytest.raises(ValueError, match=message):
        data_tools.run_imputation(ImputationRunRequest(kind=kind))


@pytest.mark.parametrize("absent", [None, pd.DataFrame()])
def test_missing_stage_keeps_legacy_fallback(absent):
    frame = pd.DataFrame({"sample": [1., 2.]})
    source, selected = functions.choose_best_source(absent, frame, frame * 10)
    assert source == "log2"
    pd.testing.assert_frame_equal(selected, frame)
    selected.iloc[0, 0] = 99
    assert frame.iloc[0, 0] == 1
    assert functions.choose_best_source(absent, None, frame)[0] == "raw"


def test_nonempty_filter_remains_preferred():
    raw = pd.DataFrame({"sample": [1., 2.]})
    filtered = raw.iloc[:1]
    source, selected = functions.choose_best_source(filtered, raw, raw)
    assert source == "filtered"
    pd.testing.assert_frame_equal(selected, filtered)
    selected.iloc[0, 0] = 99
    assert filtered.iloc[0, 0] == 1


def test_empty_percentage_filter_is_not_an_absent_stage():
    frame = pd.DataFrame({"a": [1., 2.], "b": [np.nan, np.nan]})
    meta = pd.DataFrame({"sample": ["a", "b"], "condition": ["A", "A"]})
    filtered = functions.filter_data(
        frame, meta, min_present=0, mode="per_group",
        method="percentage", min_percentage=100,
    )
    assert filtered.empty
    with pytest.raises(ValueError, match="No features passed"):
        functions.choose_best_source(filtered, frame, frame)


def test_python_notebook_keeps_empty_filtered_set(empty_filtered):
    _, frame, meta = empty_filtered
    filtered = notebook_functions.filter_data(frame, meta, num=3, mode="per_group")
    assert filtered.empty
    assert filtered.columns.tolist() == frame.columns.tolist()


def test_r_notebook_keeps_empty_filtered_set(tmp_path):
    runtime = detect_r_runtime()
    if not runtime.get("available"):
        pytest.skip("Rscript unavailable")
    script = (
        f"source('{(ROOT / 'proteomicscopylot/notebook_functions.R').as_posix()}'); "
        "d <- data.frame(ProteinNames=c('P1','P2'),a1=c(1,2),a2=c(2,3),a3=c(NA,NA)); "
        "m <- data.frame(sample=c('a1','a2','a3'),condition=c('A','A','A')); "
        "f <- filter_data(d,m,num=3,mode='per_group'); "
        "stopifnot(nrow(f)==0,identical(colnames(f),colnames(d)))"
    )
    result = subprocess.run([runtime["executable"], "-e", script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

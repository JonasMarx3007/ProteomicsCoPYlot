"""The imputed data source is the stored matrix, never recomputed or invented.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]




def test_configured_but_unmaterialized_imputation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import analysis_matrix

    class _Imputation:
        mode = "quantile"
        applied = False
        qValue = 0.01
        adjustStd = 0.3
        seed = 1337
        sampleWise = False
        downShift = 1.8
        width = 0.3

    class _Annotation:
        metadata = pd.DataFrame({"sample": ["a", "b"], "condition": ["x", "x"]})
        filtered_data = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        log2_data = filtered_data
        imputation = _Imputation()
        imputed_data = pd.DataFrame()

    monkeypatch.setattr(
        "app.services.annotation_store.get_annotation", lambda kind: _Annotation()
    )
    monkeypatch.setattr(
        "app.services.data_tools._get_current_frame", lambda kind: _Annotation.filtered_data
    )

    with pytest.raises(ValueError, match="Run imputation successfully first"):
        analysis_matrix.select_matrix("protein", data_source="imputed")


def test_imputed_request_uses_exact_stored_matrix_without_recomputing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import analysis_matrix, functions

    stored_imputed = pd.DataFrame({"a": [-10.0, 2.0], "b": [3.0, -11.0]})

    class _Imputation:
        mode = "quantile"
        applied = True

    class _Annotation:
        metadata = pd.DataFrame({"sample": ["a", "b"], "condition": ["x", "x"]})
        filtered_data = pd.DataFrame({"a": [1.0, np.nan], "b": [3.0, np.nan]})
        log2_data = filtered_data
        imputation = _Imputation()
        imputed_data = stored_imputed

    monkeypatch.setattr(
        "app.services.annotation_store.get_annotation", lambda kind: _Annotation()
    )
    monkeypatch.setattr(
        "app.services.data_tools._get_current_frame", lambda kind: _Annotation.filtered_data
    )
    monkeypatch.setattr(
        functions,
        "impute_values_with_diagnostics",
        lambda **kwargs: pytest.fail("stored imputation must not be recomputed"),
    )

    source, frame, _ = analysis_matrix.select_matrix("protein", "imputed")
    assert source == "imputed"
    pd.testing.assert_frame_equal(frame, stored_imputed)

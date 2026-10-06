"""Where imputed values are drawn from, and how their histogram is scaled.

Moved out of test_api_smoke.py (2026-10-02)."""
from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig, AnnotationImputationInfo
from app.schemas.stats import (
    AnovaRequest,
    EnrichmentRequest,
    ListEnrichmentRequest,
    VolcanoControlRequest,
)
from app.services.annotation_store import get_annotation, save_annotation
from app.services import stats_tools
from app.services.functions import impute_values_with_diagnostics
from app.services.plot_images import (
    _imputation_density_histogram_spec,
    _imputation_histogram_bin_edges,
)
from app.services.restore_state import _parse_state_blob, export_state_blob
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[3]




def test_imputation_normal_fit_plot_renders_global_and_sample_wise_draws() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    with TestClient(app) as client:
        for sample_wise in ("false", "true"):
            response = client.get(
                "/api/plots/imputation/protein/overall-fit.png",
                params={
                    "qValue": 0.01,
                    "adjustStd": 0.5,
                    "seed": 1337,
                    "sampleWise": sample_wise,
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content.startswith(b"\x89PNG")

        without_draw = client.get(
            "/api/plots/imputation/protein/overall-fit.png",
            params={"showImputationDraw": "false"},
        )
        assert without_draw.status_code == 200
        assert without_draw.content.startswith(b"\x89PNG")

        for normalization in ("together", "separate"):
            after_response = client.get(
                "/api/plots/imputation/protein/after-imputation.png",
                params={"normalization": normalization},
            )
            assert after_response.status_code == 200
            assert after_response.headers["content-type"] == "image/png"
            assert after_response.headers["cache-control"].startswith("no-store")
            assert after_response.content.startswith(b"\x89PNG")

        invalid_normalization = client.get(
            "/api/plots/imputation/protein/after-imputation.png",
            params={"normalization": "invalid"},
        )
        assert invalid_normalization.status_code == 400


def _perseus_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "s1": [10.0, 12.0, np.nan, np.nan],
            "s2": [14.0, 16.0, np.nan, np.nan],
        }
    )


def test_numerical_imputation_uses_sample_sd_shift_and_width_per_sample() -> None:
    diagnostics = impute_values_with_diagnostics(
        _perseus_frame(),
        ["s1", "s2"],
        method="numerical",
        down_shift=1.8,
        width=0.3,
        seed=1337,
    )
    np.testing.assert_allclose(
        diagnostics.draw_components,
        [(11 - 1.8 * np.sqrt(2), 0.3 * np.sqrt(2), 2),
         (15 - 1.8 * np.sqrt(2), 0.3 * np.sqrt(2), 2)],
    )
    assert diagnostics.missing_before == 4
    assert diagnostics.missing_after == 0


def test_a_dataset_wide_draw_still_uses_the_pooled_distribution() -> None:
    diagnostics = impute_values_with_diagnostics(
        _perseus_frame(),
        ["s1", "s2"],
        method="numerical",
        down_shift=1.8,
        width=0.3,
        seed=1337,
        sample_wise=False,
    )
    expected_center = diagnostics.mean - 1.8 * diagnostics.std
    expected_width = 0.3 * diagnostics.std
    assert diagnostics.draw_components == [(expected_center, expected_width, 4)]
    assert diagnostics.missing_after == 0


def test_imputation_histogram_density_normalization_preserves_area() -> None:
    non_imputed = np.array([1.0, 2.0, 3.0, 4.0])
    imputed = np.array([0.5, 1.5])

    together_edges, together_weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        "together",
    )
    together_areas = [
        float(np.sum(np.histogram(values, bins=together_edges, weights=weights)[0] * np.diff(together_edges)))
        for values, weights in zip((non_imputed, imputed), together_weights, strict=True)
    ]
    assert np.isclose(sum(together_areas), 1.0)
    assert np.isclose(together_areas[0], 4 / 6)
    assert np.isclose(together_areas[1], 2 / 6)

    separate_edges, separate_weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        "separate",
    )
    separate_areas = [
        float(np.sum(np.histogram(values, bins=separate_edges, weights=weights)[0] * np.diff(separate_edges)))
        for values, weights in zip((non_imputed, imputed), separate_weights, strict=True)
    ]
    assert np.allclose(separate_areas, [1.0, 1.0])

    overall_edges = _imputation_histogram_bin_edges(non_imputed, imputed)
    overall_density = np.histogram(non_imputed, bins=overall_edges, density=True)[0]
    separate_non_imputed_density = np.histogram(
        non_imputed,
        bins=separate_edges,
        weights=separate_weights[0],
    )[0]
    together_non_imputed_density = np.histogram(
        non_imputed,
        bins=together_edges,
        weights=together_weights[0],
    )[0]
    assert np.array_equal(overall_edges, separate_edges)
    assert np.array_equal(overall_edges, together_edges)
    assert np.allclose(separate_non_imputed_density, overall_density)
    assert np.allclose(together_non_imputed_density, overall_density * (4 / 6))

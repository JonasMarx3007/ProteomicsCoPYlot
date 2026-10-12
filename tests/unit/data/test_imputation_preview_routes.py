"""The imputation preview plots draw from their own parameters, never the stored matrix.

That is what lets the imputation page preview freely: pressing nothing stores
nothing, because each of the three plots recomputes the imputation from the
parameters in its URL. If one read a stored matrix instead, previewing would
mean applying. The page's half -- that only the button stores a run -- is
frontend/tests/component/imputation-page.test.tsx.
"""

from __future__ import annotations

import inspect

import pytest

from app.api import routes_plots

PREVIEWS = {
    "imputation_before_route": "before-missing",
    "imputation_overall_route": "overall-fit",
    "imputation_after_route": "after-imputation",
}
PARAMETERS = ("method", "qValue", "adjustStd", "downShift", "width", "seed", "sampleWise")


@pytest.mark.parametrize("route", sorted(PREVIEWS))
def test_the_preview_takes_every_imputation_parameter(route: str) -> None:
    parameters = set(inspect.signature(routes_plots.ROUTE_FUNCTIONS[route]).parameters)
    assert set(PARAMETERS) <= parameters, sorted(set(PARAMETERS) - parameters)


@pytest.mark.parametrize("route", sorted(PREVIEWS))
def test_the_preview_has_no_way_to_read_a_stored_matrix(route: str) -> None:
    assert "dataSource" not in inspect.signature(routes_plots.ROUTE_FUNCTIONS[route]).parameters


@pytest.mark.parametrize("route,path", sorted(PREVIEWS.items()))
def test_the_names_match_the_paths(route: str, path: str) -> None:
    """The functions above are the routes the page's three plots call."""
    assert routes_plots.ROUTE_PATHS[route] == f"/api/plots/imputation/{{kind}}/{path}.png"


def test_previewing_stores_nothing(client) -> None:
    """Drawing all three previews leaves the session without an imputed matrix."""
    from app.services.annotation_store import get_annotation

    before = get_annotation("protein").imputed_data.copy()
    for path in PREVIEWS.values():
        response = client.get(f"/api/plots/imputation/protein/{path}.png", params={"seed": 5})
        assert response.status_code == 200, response.text[:200]
    assert get_annotation("protein").imputed_data.equals(before)


def test_preview_and_run_resolve_the_same_imputation_matrix(monkeypatch):
    """One resolver: a raw linear zero is missing in the preview and in the run alike."""
    import numpy as np
    import pandas as pd
    from app.services import data_tools, plot_images

    raw = pd.DataFrame({"ProteinNames": ["P1", "P2"], "A1": [0.0, 5.0], "A2": [3.0, 4.0]})
    monkeypatch.setattr(data_tools, "get_annotation", lambda kind: None)
    monkeypatch.setattr(data_tools, "_get_current_frame", lambda kind: raw.copy())
    monkeypatch.setattr(data_tools, "_get_sample_columns", lambda kind, frame: ["A1", "A2"])
    source, frame, warnings = data_tools._best_imputation_source("protein")
    preview_source, preview = plot_images._imputation_source("protein")
    assert source == preview_source == "raw" and warnings
    assert np.isnan(frame.loc[0, "A1"])
    pd.testing.assert_frame_equal(frame, preview)

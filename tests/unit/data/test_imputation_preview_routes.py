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
    parameters = set(inspect.signature(getattr(routes_plots, route)).parameters)
    assert set(PARAMETERS) <= parameters, sorted(set(PARAMETERS) - parameters)


@pytest.mark.parametrize("route", sorted(PREVIEWS))
def test_the_preview_has_no_way_to_read_a_stored_matrix(route: str) -> None:
    assert "dataSource" not in inspect.signature(getattr(routes_plots, route)).parameters


@pytest.mark.parametrize("route,path", sorted(PREVIEWS.items()))
def test_the_names_match_the_paths(route: str, path: str) -> None:
    """The functions above are the routes the page's three plots call."""
    endpoints = {
        api_route.endpoint.__name__: api_route.path
        for api_route in routes_plots.router.routes
        if hasattr(api_route, "endpoint")
    }
    assert endpoints[route] == f"/api/plots/imputation/{{kind}}/{path}.png"


def test_previewing_stores_nothing(client) -> None:
    """Drawing all three previews leaves the session without an imputed matrix."""
    from app.services.annotation_store import get_annotation

    before = get_annotation("protein").imputed_data.copy()
    for path in PREVIEWS.values():
        response = client.get(f"/api/plots/imputation/protein/{path}.png", params={"seed": 5})
        assert response.status_code == 200, response.text[:200]
    assert get_annotation("protein").imputed_data.equals(before)

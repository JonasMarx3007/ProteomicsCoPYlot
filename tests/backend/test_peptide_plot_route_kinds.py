from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes_plots
from app.main import app


@pytest.mark.parametrize(
    ("path", "renderer_name"),
    [
        (
            "/api/plots/completeness/peptide/missing-value.png",
            "completeness_missing_value_plot_peptide",
        ),
        (
            "/api/plots/completeness/precursor/missing-value.png",
            "completeness_missing_value_plot_precursor",
        ),
        ("/api/plots/qc/peptide/coverage.png", "qc_peptide_coverage_plot"),
    ],
)
def test_peptide_plot_levels_reach_their_renderers(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    renderer_name: str,
) -> None:
    received: dict[str, object] = {}

    def render(**kwargs: object) -> bytes:
        received.update(kwargs)
        return b"png"

    monkeypatch.setattr(routes_plots, renderer_name, render)
    with TestClient(app) as client:
        response = client.get(path, params={"quantityColumn": "LFQ intensity"})

    assert response.status_code == 200
    assert response.content == b"png"
    assert received["quantity_column"] == "LFQ intensity"

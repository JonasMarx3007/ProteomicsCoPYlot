"""After VSN, CV and abundance read unnormalized data, and the GUI says so under the plot."""
from urllib.parse import unquote

import pytest

from app.services import data_tools


@pytest.mark.parametrize("path", ["/api/plots/qc/protein/cv.png", "/api/plots/qc/protein/abundance.png",
                                  "/api/plots/qc/protein/abundance-interactive.html"])
def test_vsn_note_is_shown_under_cv_and_abundance(client, monkeypatch, path):
    monkeypatch.setattr(data_tools, "linear_qc_uses_unnormalized", lambda kind: True)
    response = client.get(path)
    assert response.status_code == 200
    assert data_tools.VSN_LINEAR_QC_NOTICE in unquote(response.headers.get("x-copylot-notice", ""))


def test_no_note_without_vsn_or_on_other_qc_plots(client, monkeypatch):
    assert "x-copylot-notice" not in client.get("/api/plots/qc/protein/cv.png").headers
    monkeypatch.setattr(data_tools, "linear_qc_uses_unnormalized", lambda kind: True)
    assert "x-copylot-notice" not in client.get("/api/plots/qc/protein/boxplot.png").headers

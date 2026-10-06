"""Nothing this API returns may be answered from a cache.

Two halves of one promise, and they have to hold together.

**The backend** must tell the browser not to store anything under `/api/`. Every
response is a function of the session's current matrices, and those change under
the *same URL*: re-filtering or re-imputing rewrites every number without moving
an endpoint. The plot bodies have always said `no-store`. The JSON tables beside
them -- the CV table, the coverage table, the boxplot table, the completeness
tables -- carry the same numbers and said nothing at all, so the table could
come from a cache while the plot next to it was freshly rendered, and the two
would disagree on screen with nothing to say why.

**The frontend** must change the URL when the data changes. `buildPlotUrl`
appends `_dsn`, a nonce bumped by every call that replaces a matrix. Seven calls
that replace matrices did not bump it -- including `generateAnnotation`, which
is re-filtering and re-normalizing, and `runImputation`. Belt and braces: either
half alone would have been enough on a well-behaved browser, and neither was
complete. That half is tested where it lives, by calling each client:
frontend/tests/unit/dataset-scope-nonce.test.ts.
"""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from app.main import app
from app.services.viewer_bootstrap import load_viewer_state


# One of each shape: a PNG body, an HTML body, a JSON table, a JSON options
# payload, and a plain summary. The JSON ones are the ones that were bare.
ENDPOINTS = [
    "/api/plots/qc/protein/coverage.png",
    "/api/plots/qc/protein/pca-interactive.html",
    "/api/plots/qc/protein/coverage-table",
    "/api/plots/qc/protein/cv-table",
    "/api/plots/qc/protein/boxplot-table",
    "/api/plots/qc/protein/options",
    "/api/stats/options/protein",
    "/api/datasets/current",
]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_no_api_response_may_be_stored(client, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    directive = response.headers.get("cache-control", "")
    assert "no-store" in directive.lower(), (
        f"{path} may be cached ({directive!r}); re-filtering rewrites its numbers "
        "without changing its URL"
    )


def test_the_health_check_is_not_special_cased_into_caching(client) -> None:
    """`/api/health` is outside auth, but it is still under `/api/`."""
    response = client.get("/api/health")
    assert "no-store" in response.headers.get("cache-control", "").lower()

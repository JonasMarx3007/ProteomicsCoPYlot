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
complete.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

from app.main import app
from app.services.viewer_bootstrap import load_viewer_state

API_TS = ROOT / "frontend" / "src" / "lib" / "api.ts"


@pytest.fixture(scope="module")
def client():
    load_viewer_state(ROOT / "viewer_config.json")
    # The default TestClient host is `testserver`, which the host allowlist
    # refuses with a 400 that looks exactly like a broken route.
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client


# One of each shape: a PNG body, an HTML body, a JSON table, a JSON options
# payload, and a plain summary. The JSON ones are the ones that were bare.
ENDPOINTS = [
    "/api/plots/qc/protein/coverage.png",
    "/api/plots/qc/protein/pca-interactive.html",
    "/api/plots/qc/protein/coverage-table",
    "/api/plots/qc/protein/cv-table",
    "/api/plots/qc/protein/boxplot-table",
    "/api/plots/qc/protein/options",
    "/api/qc/summary/protein",
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


# --- the frontend half ---------------------------------------------------------

# Calls that replace, rebuild or re-scope a matrix. After any of these, every
# plot and table URL must be different from the one fetched before.
MUST_BUMP = [
    "uploadDataset",
    "saveTableDatasetPath",
    "importRestoreState",
    "savePeptidePath",
    "uploadPeptideFile",
    "createDatasetPackage",
    "renameDatasetPackage",
    "setActiveDatasetPackage",
    "createMetadataProfile",
    "deleteMetadataProfile",
    "renameMetadataProfile",
    "setActiveMetadataProfile",
    "updateAnnotationPairing",
    "uploadAnnotationMetadata",
    # Added after the sweep below found them missing (2026-09-25: the unused
    # clients uploadPhosprot/uploadPeptideMetadata/clearUploadedAnnotationMetadata
    # were deleted from api.ts and dropped here):
    "generateAnnotation",
    "runImputation",
    "aggregatePhosprot",
    "setConditionPalette",
    "generatePeptideMetadata",
]


def _function_body(source: str, name: str) -> str:
    start = source.index(f"export async function {name}(")
    following = re.search(r"\nexport (async )?function ", source[start + 1 :])
    end = start + 1 + (following.start() if following else len(source) - start - 1)
    return source[start:end]


@pytest.mark.parametrize("name", MUST_BUMP)
def test_every_call_that_changes_a_matrix_changes_the_urls(name: str) -> None:
    source = API_TS.read_text(encoding="utf-8")
    body = _function_body(source, name)
    assert "bumpDatasetScopeNonce()" in body, (
        f"{name} replaces a matrix but leaves `_dsn` alone, so every plot and "
        "table URL after it is byte-identical to the one fetched before"
    )


def test_the_nonce_actually_reaches_the_url() -> None:
    source = API_TS.read_text(encoding="utf-8")
    assert 'query.set("_dsn", String(DATASET_SCOPE_NONCE));' in source, (
        "the nonce is bumped but no longer appended, which is worse than neither"
    )


def test_a_failed_call_does_not_bump() -> None:
    """Bumping before the error check would discard good URLs on a 400."""
    source = API_TS.read_text(encoding="utf-8")
    for name in MUST_BUMP:
        body = _function_body(source, name)
        bump = body.index("bumpDatasetScopeNonce()")
        throws = [m.start() for m in re.finditer(r"throw new Error\(", body)]
        assert all(position < bump for position in throws), (
            f"{name} bumps the nonce before it knows the call succeeded"
        )

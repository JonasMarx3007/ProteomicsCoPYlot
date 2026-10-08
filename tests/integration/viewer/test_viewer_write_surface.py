"""Every write the API exposes is either denied to a viewer or listed here.

Viewer mode is enforced by two deny lists in `app.main`. A deny list is only as
good as the last person who remembered to add to it, and the failure is silent:
the endpoint keeps working, the UI still hides the page, and nothing says the
gate is not covering it. That is how `POST /api/data-tools/imputation/download`
came to run the same imputation as `/run` -- which *is* denied -- and hand back
the whole filled matrix, from a deployment whose Imputation tab is not there.

So this test inverts the question. It enumerates every mutating method the
application actually serves, and requires each one to be either denied or named
below with a reason. A new write route fails this test until someone decides
which it is. That decision is cheap to make and expensive to forget.

The read side is deliberately not covered: a viewer is allowed to read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.main import (
    _VIEWER_DENIED_EXACT,
    _VIEWER_DENIED_PREFIXES,
    _auth_route,
    app,
)

WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# Writes a viewer is allowed to make, and why. Everything here was read and
# decided on; nothing is here because it happened to be reachable.
ALLOWED: dict[tuple[str, str], str] = {
    # Analysis that computes and returns, touching no stored state. These are
    # POSTs only because their request bodies are too large for a query string.
    ("POST", "/api/analysis/volcano/data"): "computes volcano points, stores nothing",
    ("POST", "/api/stats/volcano/run"): "computes a volcano, stores nothing",
    ("POST", "/api/stats/volcano-control/run"): "computes a contrast, stores nothing",
    ("POST", "/api/stats/anova/run"): "computes an ANOVA, stores nothing",
    ("POST", "/api/stats/ora/run"): "computes an enrichment, stores nothing",
    ("POST", "/api/stats/ora/list/run"): "computes an enrichment, stores nothing",
    ("POST", "/api/stats/simulation/run"): "computes a hypothetical, stores nothing",
    ("POST", "/api/summary/report"): "renders the report a viewer is here to read",
    ("POST", "/api/plots/phospho/ksea-volcano.html"): "renders an uploaded KSEA result",
    ("POST", "/api/annotations/log2-detect"): "inspects a frame's scale, stores nothing",
    # Choosing which published dataset to look at. A viewer project may hold
    # several; picking one is what the selector is for.
    ("POST", "/api/datasets/active"): "switches between published datasets",
    ("POST", "/api/datasets/metadata/profiles/active"): "switches published profiles",
    # Which phosphosites this session's plots show; the published data is untouched.
    ("POST", "/api/data-tools/phospho-localization-cutoff"): "chooses the localization cutoff to view",
    # Session lifecycle.
    ("POST", "/api/restore/browser-session-reset"): "resets this browser's session",
    # Reviewed and left open on purpose; see the review report's security
    # appendix, where each is written up with the argument on both sides.
    ("POST", "/api/chat/assistant"): "the assistant is offered in viewer builds",
    ("POST", "/api/chat/local-models"): "reads a local AI server's model list; a POST only so a key stays out of URLs",
    ("POST", "/api/chat/cloud-consent/{provider}/grant"): "consent for that assistant",
    ("POST", "/api/chat/cloud-consent/{provider}/revoke"): "withdrawing it",
}


def _served_writes() -> set[tuple[str, str]]:
    """Every mutating operation in the served OpenAPI document."""
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method.upper() in WRITE_METHODS and path.startswith("/api/")
    }


def _denied(method: str, path: str) -> bool:
    if (method, path) in _VIEWER_DENIED_EXACT:
        return True
    return any(
        method == denied_method and path.startswith(prefix)
        for denied_method, prefix in _VIEWER_DENIED_PREFIXES
    )


def test_every_write_is_denied_or_deliberately_allowed() -> None:
    unclassified = sorted(
        operation
        for operation in _served_writes()
        if not _denied(*operation)
        and operation not in ALLOWED
        and not _auth_route(operation[1])
    )
    assert not unclassified, (
        "these writes are reachable in viewer mode and nobody has said whether "
        "they should be. Add each to the deny list in app.main, or to ALLOWED "
        "here with the reason:\n  "
        + "\n  ".join(f"{method} {path}" for method, path in unclassified)
    )


def test_the_allow_list_has_not_outlived_its_routes() -> None:
    """An entry for a route that no longer exists hides the next question."""
    served = _served_writes()
    stale = sorted(operation for operation in ALLOWED if operation not in served)
    assert not stale, f"ALLOWED names routes the app no longer serves: {stale}"


def test_the_allow_list_does_not_contradict_the_deny_list() -> None:
    both = sorted(operation for operation in ALLOWED if _denied(*operation))
    assert not both, f"listed as allowed and denied at once: {both}"


@pytest.mark.parametrize(
    "operation",
    [
        ("POST", "/api/data-tools/imputation/run"),
        ("POST", "/api/data-tools/imputation/download"),
        # Writes the translated table into the session as a dataset.
        ("POST", "/api/data-tools/id-translation/run"),
        ("POST", "/api/data-tools/id-translation/download"),
        ("POST", "/api/data-tools/condition-colors/protein"),
        ("POST", "/api/datasets/upload"),
        ("POST", "/api/annotations/generate"),
        ("POST", "/api/restore/import"),
        ("POST", "/api/restore/export"),
        ("DELETE", "/api/annotations/metadata/current/protein"),
    ],
    ids=lambda operation: f"{operation[0]} {operation[1]}",
)
def test_the_data_processing_writes_stay_denied(operation: tuple[str, str]) -> None:
    """Named individually, because these are the ones that must never drift."""
    assert _denied(*operation), f"{operation[0]} {operation[1]} is reachable in viewer mode"


def test_reading_the_palette_is_still_allowed() -> None:
    """Denying the write must not take the read with it."""
    assert not _denied("GET", "/api/data-tools/condition-colors/protein")


def test_viewers_download_plots_but_not_notebooks() -> None:
    """Every notebook ZIP carries the exact input matrix; a viewer reads figures."""
    assert _denied("GET", "/api/plots/notebooks/abcdefghijklmnopqrstuvwxyz012345.zip")
    assert not _denied("GET", "/api/plots/qc/protein/boxplot.png")


def test_a_viewer_render_offers_no_notebook(client, monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_VIEWER_MODE", "1")
    response = client.get("/api/plots/qc/protein/boxplot.png")
    assert response.status_code == 200
    assert "x-copylot-notebook" not in response.headers

from __future__ import annotations

import html
import io
import logging
import pathlib

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.services import stats_tools

# How route handlers and services may phrase errors -- no exception text in a
# response, every 500 logged, no filesystem path in a 400 -- is a code-shape
# rule, checked by tools/check_backend_rules.py (tests/repo/test_backend_code_rules.py).


# Each unauthenticated auth endpoint, with the service behind it failing in a way
# whose message describes the server's configuration. The route module's own
# references are replaced, so the request goes through the real handler.
SECRET = "/srv/copylot/secret/access_config.json"


@pytest.mark.parametrize('expected', [True, False])
def test_save_export_errors_do_not_expose_exception_text(monkeypatch, caplog, expected):
    from app.api import routes_restore
    from app.services.restore_state import RestoreStateError

    def fail(**kwargs):
        raise (RestoreStateError if expected else RuntimeError)(f"Cannot export {SECRET}")

    monkeypatch.setattr(routes_restore, 'export_state_blob', fail)
    with caplog.at_level(logging.ERROR), TestClient(app) as client:
        response = client.post('/api/restore/export', json={})
    assert response.status_code == (400 if expected else 500)
    assert SECRET not in response.text
    assert 'Cannot export' not in response.text
    assert SECRET in caplog.text


AUTH_FAILURES = [
    ("routes_tool_auth", "tool_access_enabled", "authenticate_tool_password",
     "post", "/api/tool/auth/login", {"password": "x"}),
    ("routes_tool_auth", "tool_access_enabled", "authenticate_tool_token",
     "post", "/api/tool/auth/link-login", {"token": "x"}),
    ("routes_viewer_auth", "viewer_portal_enabled", "authenticate_viewer_session",
     "post", "/api/viewer/auth/login", {"password": "x"}),
    ("routes_viewer_auth", "viewer_portal_enabled", "authenticate_viewer_qr_session",
     "post", "/api/viewer/auth/qr-login", {"token": "x"}),
    ("routes_viewer_auth", "viewer_portal_enabled", "ensure_viewer_session_bootstrapped",
     "get", "/api/viewer/auth/status", None),
]


@pytest.mark.parametrize("error", [FileNotFoundError, RuntimeError], ids=["missing config", "unexpected"])
@pytest.mark.parametrize(
    "module_name,enabled,service,method,url,body", AUTH_FAILURES, ids=[row[4] for row in AUTH_FAILURES]
)
def test_unauthenticated_auth_endpoints_do_not_describe_their_configuration(
    monkeypatch, caplog, module_name, enabled, service, method, url, body, error
) -> None:
    import importlib

    module = importlib.import_module(f"app.api.{module_name}")

    def fail(*args, **kwargs):
        raise error(f"cannot read {SECRET}")

    monkeypatch.setattr(module, enabled, lambda: True)
    monkeypatch.setattr(module, service, fail)
    monkeypatch.setattr(module.LOGIN_RATE_LIMIT, "enforce", lambda *args, **kwargs: None)
    if module_name == "routes_viewer_auth":
        monkeypatch.setattr(module, "viewer_session_auth", lambda: object())
        monkeypatch.setattr(module, "clear_viewer_session_auth", lambda **kwargs: None)

    with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as client:
        response = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert response.status_code == 500
    assert SECRET not in response.text, f"{url} describes the server's configuration: {response.text}"
    assert "secret" not in response.text.lower()
    # Every route logs why, whatever failed (the tool-access logins once let an
    # unexpected error through to the server's generic page unlogged).
    assert SECRET in caplog.text, f"{url} answered 500 without logging why"


def test_report_body_carries_no_exception_text(example_project, monkeypatch, caplog) -> None:
    """A figure that fails to render leaves a neutral note where the figure was.

    Every figure and summary table is made to fail with a recognisable message.
    The report still renders, and each failed slot says only that it could not
    be rendered. The report has no warnings section: warnings go back to the
    page that asked for the report, naming what failed, and the reason is in the
    server log -- an exception string can carry a path or someone's data.
    """
    from app.schemas.summary import SummaryReportContext, SummaryReportRequest
    from app.services import report_function as module

    secret = "Traceback: /home/analyst/private/project.tsv"

    def fail(renderer, *args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(module, "report_plot", fail)
    monkeypatch.setattr(module, "report_table", fail)
    context = SummaryReportContext(qcSettings={"protein": {
        "coverage": {"summary": True}, "pca": {"type": "Interactive"}, "box": {"mode": "Single"},
    }})
    with caplog.at_level(logging.ERROR):
        result = module.report_function(SummaryReportRequest(title="T", author="A", reportContext=context))

    assert "Report Warnings" not in result.html, "warnings belong in the page, not the report"
    assert secret not in result.html and html.escape(secret) not in result.html
    assert "Could not render this plot" in result.html
    assert "Could not render this interactive plot" in result.html
    assert "Could not render this summary table" in result.html
    # One warning for every figure that shows the note, naming it and not the reason.
    failed = result.html.count("Could not render this")
    assert failed >= 3
    assert sum(warning.endswith("could not be rendered.") for warning in result.warnings) == failed, result.warnings
    assert not any(secret in warning for warning in result.warnings)
    assert secret in caplog.text, "the reason is logged for whoever runs the server"


def test_a_refused_figure_tells_the_page_why(example_project, monkeypatch) -> None:
    """A renderer's own refusal (a ValueError) is the answer, as on the plot pages."""
    from app.schemas.summary import SummaryReportContext, SummaryReportRequest
    from app.services import report_function as module

    def refuse(renderer, *args, **kwargs):
        raise ValueError("Select at least two samples.")

    monkeypatch.setattr(module, "report_plot", refuse)
    context = SummaryReportContext(qcSettings={"protein": {"box": {"mode": "Single"}}})
    result = module.report_function(SummaryReportRequest(title="T", author="A", reportContext=context))
    assert any(warning.endswith("could not be rendered: Select at least two samples.") for warning in result.warnings)
    assert "Select at least two samples." not in result.html


def test_missing_database_reports_usefully_without_disclosing_paths() -> None:
    secret = pathlib.Path(r"C:\Users\SomeUser\AppData\Local\proteomics-copylot\db\x.csv")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("app.services.stats_tools")
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        with TestClient(app) as client:
            with patch.object(stats_tools, "_go_db_candidates", return_value=[secret]):
                stats_tools.load_go_db.cache_clear()
                response = client.get("/api/stats/pathways")
    finally:
        logger.removeHandler(handler)
        stats_tools.load_go_db.cache_clear()

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "all_go_terms_genes.csv" in detail
    assert "SomeUser" not in response.text
    assert "AppData" not in response.text
    assert "SomeUser" in stream.getvalue()

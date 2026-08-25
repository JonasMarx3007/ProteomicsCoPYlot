from __future__ import annotations

import io
import logging
import pathlib
import re
import sys

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app
from app.services import stats_tools

ROUTES = sorted((ROOT / "backend" / "app" / "api").glob("routes_*.py"))
SERVICES = sorted((ROOT / "backend" / "app" / "services").glob("*.py"))


@pytest.mark.parametrize("path", ROUTES, ids=lambda p: p.name)
def test_no_500_handler_interpolates_the_exception(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "status_code=500" in line and ("{e}" in line or "{exc}" in line)
    ]
    assert not offenders, f"{path.name} returns raw exception text: {offenders[:2]}"


@pytest.mark.parametrize("path", ROUTES, ids=lambda p: p.name)
def test_no_handler_interpolates_a_generic_exception(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "detail=f" in line and ("{e}" in line or "{exc}" in line)
    ]
    assert not offenders, f"{path.name} returns raw exception text: {offenders[:2]}"


@pytest.mark.parametrize("path", ROUTES, ids=lambda p: p.name)
def test_every_500_response_is_logged(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    responses = source.count("status_code=500")
    if responses == 0:
        return
    assert "LOGGER = logging.getLogger(__name__)" in source, f"{path.name} has no logger"
    logged = source.count("LOGGER.exception(")
    assert logged >= responses, (
        f"{path.name}: {responses} 500 responses but only {logged} log calls"
    )


def test_unauthenticated_auth_endpoints_do_not_describe_their_configuration() -> None:
    for name in ("routes_tool_auth.py", "routes_viewer_auth.py"):
        source = (ROOT / "backend" / "app" / "api" / name).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if "status_code=500" in line and "str(exc)" in line
        ]
        assert not offenders, f"{name} returns raw error text pre-authentication: {offenders}"


@pytest.mark.parametrize("path", SERVICES, ids=lambda p: p.name)
def test_no_service_error_message_embeds_a_filesystem_path(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'raise ValueError\(\s*f?"[^"]*\{(?:path|searched|candidate|full_path)\}',
        re.MULTILINE,
    )
    offenders = pattern.findall(source)
    assert not offenders, f"{path.name} puts a path in a user-facing message: {offenders[:2]}"


def test_report_body_carries_no_exception_text() -> None:
    source = (ROOT / "backend" / "app" / "services" / "report_function.py").read_text(
        encoding="utf-8"
    )
    assert "escape(str(exc))" not in source
    assert source.count('warnings.append(f"{fallback_title}: {exc}")') >= 3


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

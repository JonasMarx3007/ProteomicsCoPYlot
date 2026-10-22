from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_runtime


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("peer,headers,settings,hidden", [
    ("127.0.0.1", {}, {}, False),
    ("::1", {}, {}, False),
    ("::ffff:127.0.0.1", {}, {}, False),
    ("198.51.100.10", {}, {}, True),
    ("198.51.100.10", {"x-forwarded-for": "127.0.0.1"}, {}, True),
    ("127.0.0.1", {"x-forwarded-for": "198.51.100.10"}, {}, True),
    ("127.0.0.1", {"forwarded": "for=127.0.0.1"}, {}, True),
    ("127.0.0.1", {}, {"COPYLOT_TRUSTED_PROXY_IPS": "127.0.0.1/32"}, True),
    ("127.0.0.1", {"x-forwarded-for": "malformed"}, {"COPYLOT_TRUSTED_PROXY_IPS": "127.0.0.1/32"}, True),
    ("127.0.0.1", {}, {"COPYLOT_VIEWER_MODE": "1"}, True),
    ("127.0.0.1", {}, {"COPYLOT_VIEWER_PORTAL_ENABLED": "1"}, True),
    ("127.0.0.1", {}, {"COPYLOT_TOOL_ACCESS_ENABLED": "1", "COPYLOT_ALLOW_LOCAL_PATH_APIS": "1"}, True),
    ("unknown", {}, {}, True),
])
def test_runtime_diagnostics_visibility(monkeypatch, available, peer, headers, settings, hidden):
    for name in ("COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED", "COPYLOT_TOOL_ACCESS_ENABLED",
                 "COPYLOT_TRUSTED_PROXY_IPS", "COPYLOT_ALLOW_LOCAL_PATH_APIS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    runtime = {
        "available": available,
        "executable": "C:/Users/private-user/R/bin/Rscript.exe" if available else None,
        "version": "4.5.1" if available else None,
        "versionOutput": "Rscript version 4.5.1; /srv/private-user/runtime" if available else None,
        "detectedFrom": "env" if available else None,
        "candidates": ["C:/Users/private-user/R/bin/Rscript.exe", "/srv/private-user/Rscript"],
        "error": None if available else "/srv/private-user/Rscript: permission denied",
    }
    original = deepcopy(runtime)
    monkeypatch.setattr(routes_runtime, "detect_r_runtime", lambda: runtime)
    refreshed = []
    for name in ("clear_r_runtime_cache", "clear_vsn_availability_cache", "clear_limma_availability_cache"):
        monkeypatch.setattr(routes_runtime, name, lambda: refreshed.append(True))
    app = FastAPI()
    app.include_router(routes_runtime.router)
    with TestClient(app, client=(peer, 12345)) as client:
        response = client.get("/api/runtime/r?refresh=true", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] == available
    assert body["version"] == runtime["version"]
    assert body["diagnosticsHidden"] == hidden
    if hidden:
        assert "private-user" not in response.text
        assert body["candidates"] == []
        assert body["executable"] is body["versionOutput"] is body["detectedFrom"] is None
        assert body["error"] == (None if available else "R runtime is unavailable. Contact the deployment administrator.")
    else:
        assert body == {**runtime, "diagnosticsHidden": False}
    assert runtime == original
    assert len(refreshed) == 3


@pytest.mark.parametrize("endpoint,probe,version,field", [
    ("normalization", "vsn_availability", "vsn_reference_version", "vsnUnavailableReason"),
    ("statistics", "limma_availability", "limma_reference_version", "moderatedUnavailableReason"),
])
@pytest.mark.parametrize("peer,hidden", [("127.0.0.1", False), ("198.51.100.10", True)])
def test_capability_errors_do_not_expose_server_paths(monkeypatch, endpoint, probe, version, field, peer, hidden):
    for name in ("COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED", "COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_TRUSTED_PROXY_IPS"):
        monkeypatch.delenv(name, raising=False)
    reason = "Could not query /srv/private-user/Rscript: permission denied"
    monkeypatch.setattr(routes_runtime, probe, lambda: {"available": False, "reason": reason})
    monkeypatch.setattr(routes_runtime, version, lambda: None)
    app = FastAPI()
    app.include_router(routes_runtime.router)
    with TestClient(app, client=(peer, 12345)) as client:
        response = client.get(f"/api/runtime/{endpoint}")
    assert response.status_code == 200
    if hidden:
        assert "private-user" not in response.text
        assert "administrator" in response.json()[field]
    else:
        assert response.json()[field] == reason

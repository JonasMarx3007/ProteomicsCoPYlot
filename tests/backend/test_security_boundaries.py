from __future__ import annotations

import gzip
import json
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.routes_tool_auth import _client_key as tool_client_key
from app.api.routes_viewer_auth import _client_key as viewer_client_key
from app.main import (
    _authentication_configuration_error,
    _remote_local_path_request_denied,
    _viewer_request_denied,
    app,
)
from app.services.chat_tools import _normalize_ollama_endpoint
from app.services.session_context import session_isolation_enabled
from app.services.password_hashing import hash_password, verify_password
from app.services.restore_state import RestoreStateError, decode_restore_blob
import launch
from launch import _host_is_loopback, _validate_network_binding


def _request(
    method: str,
    path: str,
    *,
    forwarded_for: str | None = None,
    client_host: str = "10.0.0.5",
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": (client_host, 12345),
            "server": ("example.test", 443),
        }
    )


def test_protected_deployments_fail_closed_without_session_isolation(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    assert "COPYLOT_SESSION_ISOLATION=1" in (_authentication_configuration_error() or "")


def test_session_isolation_is_on_unless_it_is_explicitly_turned_off(monkeypatch) -> None:
    monkeypatch.delenv("COPYLOT_SESSION_ISOLATION", raising=False)
    assert session_isolation_enabled(), (
        "session isolation must default on; with it off every browser shares one "
        "state and a second user reads and overwrites the first one's upload"
    )
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    assert _authentication_configuration_error() is None


def test_viewer_policy_blocks_mutation_but_allows_analysis() -> None:
    assert _viewer_request_denied(_request("POST", "/api/datasets/upload"))
    assert _viewer_request_denied(_request("DELETE", "/api/annotations/metadata/current/protein"))
    assert _viewer_request_denied(_request("PUT", "/api/annotations/pairing"))
    assert not _viewer_request_denied(_request("POST", "/api/stats/volcano/run"))


def test_standalone_viewer_enforces_read_only_policy_without_isolation(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_VIEWER_MODE", "1")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    with TestClient(app) as client:
        response = client.post(
            "/api/datasets/packages/create",
            json={"packageName": "must-not-be-created"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "This operation is disabled in read-only viewer mode."
        assert client.get("/api/health").status_code == 200


def test_remote_tool_policy_blocks_server_local_paths(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.delenv("COPYLOT_ALLOW_LOCAL_PATH_APIS", raising=False)
    assert _remote_local_path_request_denied(_request("POST", "/api/datasets/table-path"))
    assert not _remote_local_path_request_denied(_request("POST", "/api/datasets/upload"))


@pytest.mark.parametrize(
    "path",
    [
        "/api/datasets/table-path",
        "/api/datasets/peptide-path",
        "/api/external/peptide-collapse/run",
        "/api/restore/import",
    ],
)
def test_remote_local_path_operations_are_blocked_without_authentication(
    monkeypatch,
    path: str,
) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_ALLOW_LOCAL_PATH_APIS", "1")
    assert _remote_local_path_request_denied(_request("POST", path))


@pytest.mark.parametrize(
    "path",
    [
        "/api/datasets/table-path",
        "/api/datasets/peptide-path",
        "/api/external/peptide-collapse/run",
        "/api/restore/import",
    ],
)
def test_http_middleware_denies_remote_local_path_operations(
    monkeypatch,
    path: str,
) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    with TestClient(app, client=("198.51.100.10", 50000)) as client:
        response = client.post(path)
    assert response.status_code == 403
    assert "unavailable to remote clients" in response.json()["detail"]


def test_unprotected_loopback_client_can_use_local_path_operations(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    assert not _remote_local_path_request_denied(
        _request("POST", "/api/datasets/table-path", client_host="127.0.0.1")
    )
    assert not _remote_local_path_request_denied(
        _request("POST", "/api/datasets/table-path", client_host="::1")
    )


def test_trusted_loopback_proxy_cannot_hide_a_remote_client(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "127.0.0.1")
    request = _request(
        "POST",
        "/api/datasets/table-path",
        client_host="127.0.0.1",
        forwarded_for="198.51.100.99",
    )
    assert _remote_local_path_request_denied(request)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.2.3.4", "::1", "localhost", "LOCALHOST."])
def test_launcher_recognizes_loopback_hosts(host: str) -> None:
    assert _host_is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20", "copylot.example"])
def test_launcher_rejects_unprotected_non_loopback_bind(monkeypatch, host: str) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    with pytest.raises(ValueError, match="Refusing to bind"):
        _validate_network_binding(host, allow_unsafe_public=False)


def test_launcher_requires_authentication_and_isolation_together(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    with pytest.raises(ValueError, match="session isolation"):
        _validate_network_binding("0.0.0.0", allow_unsafe_public=False)

    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    _validate_network_binding("0.0.0.0", allow_unsafe_public=False)


def test_launcher_unsafe_override_is_explicit_and_warns(monkeypatch, capsys) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    _validate_network_binding("0.0.0.0", allow_unsafe_public=True)
    assert "WARNING" in capsys.readouterr().err


def test_launcher_cli_stops_before_starting_unprotected_public_server(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "0")
    monkeypatch.setattr(
        sys,
        "argv",
        ["launch.py", "--host", "0.0.0.0", "--no-browser"],
    )
    with pytest.raises(SystemExit) as excinfo:
        launch.main()
    assert excinfo.value.code == 2
    assert "Refusing to bind" in capsys.readouterr().err


def test_login_rate_limit_key_ignores_spoofed_forwarded_header() -> None:
    request = _request("POST", "/api/tool/auth/login", forwarded_for="198.51.100.99")
    assert tool_client_key(request) == "10.0.0.5"
    assert viewer_client_key(request) == "10.0.0.5"


def test_login_rate_limit_honors_forwarded_header_from_explicit_proxy(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "10.0.0.5")
    request = _request("POST", "/api/tool/auth/login", forwarded_for="198.51.100.99")
    assert tool_client_key(request) == "198.51.100.99"
    assert viewer_client_key(request) == "198.51.100.99"


def test_pbkdf2_password_hash_round_trip_and_iteration_cap() -> None:
    encoded = hash_password("correct horse battery staple", iterations=100_000)
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    with pytest.raises(ValueError, match="parameters"):
        verify_password("password", "2000001$00112233445566778899aabbccddeeff$" + "11" * 32)


def test_protected_backend_rejects_shell_bypass_and_anonymous_session_flood(
    monkeypatch,
    tmp_path,
) -> None:
    access_file = tmp_path / "tool_access.json"
    access_file.write_text(
        json.dumps(
            {
                "password_pbkdf2_sha256": hash_password("test-password", iterations=100_000),
                "tokens": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access_file))
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    monkeypatch.setenv("COPYLOT_MAX_SESSIONS", "1")
    monkeypatch.delenv("COPYLOT_VIEWER_PORTAL_ENABLED", raising=False)

    session_id = "authenticated_session"
    with TestClient(app) as client:
        client.cookies.clear()
        denied = client.get(
            "/api/datasets/current",
            headers={"X-CoPYlot-Session": session_id},
        )
        assert denied.status_code == 401

        client.cookies.clear()
        login = client.post(
            "/api/tool/auth/login",
            headers={"X-CoPYlot-Session": session_id},
            json={"password": "test-password"},
        )
        assert login.status_code == 200

        for index in range(4):
            client.cookies.clear()
            assert client.get(
                "/api/health",
                headers={"X-CoPYlot-Session": f"anonymous_session_{index}"},
            ).status_code == 200

        client.cookies.clear()
        allowed = client.get(
            "/api/datasets/current",
            headers={"X-CoPYlot-Session": session_id},
        )
        assert allowed.status_code == 200

        client.cookies.clear()
        near_miss = client.get(
            "/api/tool/auth-bypass",
            headers={"X-CoPYlot-Session": "unknown_session"},
        )
        assert near_miss.status_code == 401


def test_invalid_auth_combinations_and_placeholder_credentials_fail_closed(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    assert "cannot be enabled in the same process" in (
        _authentication_configuration_error() or ""
    )

    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    access_file = tmp_path / "tool_access.json"
    access_file.write_text(
        json.dumps({"password_sha256": "0" * 64, "tokens": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access_file))
    assert "example placeholder" in (_authentication_configuration_error() or "")


def test_passive_security_headers_do_not_restrict_embedding(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "0")
    monkeypatch.setenv("COPYLOT_VIEWER_PORTAL_ENABLED", "0")
    with TestClient(app) as client:
        response = client.get("/api/tool/auth/status")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "x-frame-options" not in response.headers
    assert "content-security-policy" not in response.headers


def test_ollama_override_requires_local_or_explicitly_allowed_origin(monkeypatch) -> None:
    monkeypatch.delenv("COPYLOT_OLLAMA_URL", raising=False)
    monkeypatch.delenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", raising=False)
    assert _normalize_ollama_endpoint("localhost:11434") == "http://localhost:11434"
    with pytest.raises(ValueError, match="not allowed"):
        _normalize_ollama_endpoint("http://169.254.169.254/latest")

    monkeypatch.setenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", "https://ollama.example:11434")
    assert (
        _normalize_ollama_endpoint("https://ollama.example:11434/api/chat")
        == "https://ollama.example:11434/api/chat"
    )


def test_restore_gzip_expansion_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_RESTORE_UPLOAD_MAX_BYTES", "1024")
    monkeypatch.setenv("COPYLOT_RESTORE_EXPANDED_MAX_BYTES", "32")
    compressed = gzip.compress(b"x" * 128)
    with pytest.raises(RestoreStateError, match="Expanded restore state"):
        decode_restore_blob(compressed)

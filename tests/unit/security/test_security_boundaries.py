from __future__ import annotations

import gzip
import json
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.routes_tool_auth import LOGIN_RATE_LIMIT as tool_login_rate_limit
from app.api.routes_viewer_auth import LOGIN_RATE_LIMIT as viewer_login_rate_limit
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



def _rotated_session_id(response, cookie_name: str = "copylot_session_id") -> str:
    """The session id a login handed out, read the way a client reads it.

    From the `Set-Cookie` header, not the response body. A browser takes it as an
    HttpOnly cookie it cannot read; a header-based client reads the same header
    directly. Neither needs it echoed in the JSON, and putting it there gave a
    live authenticated session to anything that could read a response.
    """
    for key, value in response.headers.raw:
        if key.lower() != b"set-cookie":
            continue
        text = value.decode("latin-1").lstrip()
        if text.startswith(f"{cookie_name}="):
            return text.split("=", 1)[1].split(";", 1)[0]
    raise AssertionError(f"login set no {cookie_name} cookie: {response.headers.raw}")


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
    assert _authentication_configuration_error(validate_credentials=False) is None


def test_viewer_policy_blocks_mutation_but_allows_analysis() -> None:
    assert _viewer_request_denied(_request("POST", "/api/datasets/upload"))
    assert _viewer_request_denied(_request("DELETE", "/api/annotations/metadata/current/protein"))
    assert _viewer_request_denied(
        _request("DELETE", "/api/datasets/metadata/profiles/delete")
    )
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


def _limiter_key(limiter, request: Request) -> str:
    """The address the limiter counts against, read off the bucket it creates."""
    limiter.attempts.clear()
    limiter.enforce(request, bucket="probe")
    (key,) = limiter.attempts
    limiter.attempts.clear()
    return key[0]


def test_login_rate_limit_key_ignores_spoofed_forwarded_header() -> None:
    request = _request("POST", "/api/tool/auth/login", forwarded_for="198.51.100.99")
    assert _limiter_key(tool_login_rate_limit, request) == "10.0.0.5"
    assert _limiter_key(viewer_login_rate_limit, request) == "10.0.0.5"


def test_login_rate_limit_honors_forwarded_header_from_explicit_proxy(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "10.0.0.5")
    request = _request("POST", "/api/tool/auth/login", forwarded_for="198.51.100.99")
    assert _limiter_key(tool_login_rate_limit, request) == "198.51.100.99"
    assert _limiter_key(viewer_login_rate_limit, request) == "198.51.100.99"


def test_the_two_login_realms_count_separately() -> None:
    """One shared limiter class, but a budget each: filling the viewer portal's
    must not lock the tool out."""
    assert tool_login_rate_limit.attempts is not viewer_login_rate_limit.attempts


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
        # Authentication rotates the session id. A header-based client adopts the
        # new one from the `Set-Cookie` response header -- which it can read even
        # though it stores no cookies. It is deliberately not in the response
        # body: that copy was readable by anything that could read a response.
        assert "sessionId" not in login.json()
        session_id = _rotated_session_id(login)

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


@pytest.mark.parametrize("mode", ["tool", "viewer"])
def test_anonymous_public_requests_do_not_evict_protected_sessions(monkeypatch, mode):
    import time
    import pandas as pd
    from app.services import session_cleanup, tool_access, viewer_portal, dataset_store
    from app.services.session_context import set_session_id, reset_session_id

    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_ENABLED', str(int(mode == 'tool')))
    monkeypatch.setenv('COPYLOT_VIEWER_PORTAL_ENABLED', str(int(mode == 'viewer')))
    monkeypatch.setenv('COPYLOT_VIEWER_MODE', str(int(mode == 'viewer')))
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    monkeypatch.setenv('COPYLOT_MAX_SESSIONS', '1')
    monkeypatch.setenv('COPYLOT_SESSION_IDLE_SECONDS', '60')
    victim = 'synthetic_authenticated_session'
    auth = viewer_portal.ViewerSessionAuth(project='synthetic', project_label='Synthetic')
    monkeypatch.setattr(session_cleanup, '_LAST_SEEN', {victim: time.monotonic()})
    monkeypatch.setattr(tool_access, '_SESSION_AUTH', {victim} if mode == 'tool' else set())
    monkeypatch.setattr(viewer_portal, '_SESSION_AUTH', {victim: auth} if mode == 'viewer' else {})
    monkeypatch.setattr(dataset_store, '_DATASET_SESSIONS', {})
    monkeypatch.setattr('app.main.ensure_viewer_session_bootstrapped', lambda **kw: auth)
    monkeypatch.setattr('app.api.routes_viewer_auth.ensure_viewer_session_bootstrapped', lambda **kw: auth)
    token = set_session_id(victim)
    try:
        dataset_store.save_table_dataset('private.csv', 'protein', pd.DataFrame({'ProteinNames': ['PRIVATE']}))
    finally:
        reset_session_id(token)

    # Skip lifespan: grants are synthetic; no credential files or viewer project are needed.
    client = TestClient(app)
    for index, path in enumerate(['/api/health', '/api/tool/auth/status', '/api/viewer/auth/status'] * 2):
        client.cookies.clear()
        assert client.get(path, headers={'X-CoPYlot-Session': f'anonymous_session_{index}'}).status_code == 200
        assert set(session_cleanup._LAST_SEEN) == {victim}
        assert victim in dataset_store._DATASET_SESSIONS
    client.cookies.clear()
    headers = {'X-CoPYlot-Session': victim}
    before = session_cleanup._LAST_SEEN[victim]
    assert client.get('/api/datasets/current', headers=headers).status_code == 200
    assert session_cleanup._LAST_SEEN[victim] >= before
    session_cleanup._LAST_SEEN[victim] -= 61
    assert client.get('/api/datasets/current', headers=headers).status_code == 401
    assert victim not in session_cleanup._LAST_SEEN
    assert victim not in dataset_store._DATASET_SESSIONS


def test_a_browser_that_only_has_cookies_stays_logged_in_after_rotation(
    monkeypatch,
    tmp_path,
) -> None:
    """Login must hand back exactly one session cookie.

    Authentication rotates the session id and the login route sets the rotated
    one. The middleware resolved its own id before the route ran, so it used to
    append a second cookie carrying the pre-rotation id; last-wins left the
    browser holding the unauthenticated one. Header-based clients were fine,
    which is why the fixation test above never saw it.
    """
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
    monkeypatch.delenv("COPYLOT_VIEWER_PORTAL_ENABLED", raising=False)

    with TestClient(app) as client:
        client.cookies.clear()
        login = client.post("/api/tool/auth/login", json={"password": "test-password"})
        assert login.status_code == 200

        handed_out = [
            value.decode("latin-1")
            for key, value in login.headers.raw
            if key.lower() == b"set-cookie"
            and value.lstrip().startswith(b"copylot_session_id=")
        ]
        assert len(handed_out) == 1, f"login set {len(handed_out)} session cookies: {handed_out}"
        assert client.cookies.get("copylot_session_id") == _rotated_session_id(login)

        assert client.get("/api/datasets/current").status_code == 200


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
        json.dumps({"password_pbkdf2_sha256": "600000$" + "0" * 32 + "$" + "0" * 64, "tokens": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access_file))
    assert "placeholder" in (_authentication_configuration_error() or "")


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


@pytest.mark.parametrize('mode,method', [('tool', 'login'), ('tool', 'link-login'), ('viewer', 'login'), ('viewer', 'qr-login')])
@pytest.mark.parametrize('tab', ['', 'a' * 32])
def test_login_registers_rotated_session_without_followup(monkeypatch, mode, method, tab):
    import hashlib
    import pandas as pd
    from app.services import session_cleanup as cleanup, tool_access, viewer_portal as viewer, dataset_store
    from app.services.session_context import set_session_id, reset_session_id

    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_ENABLED', str(int(mode == 'tool')))
    monkeypatch.setenv('COPYLOT_VIEWER_PORTAL_ENABLED', str(int(mode == 'viewer')))
    monkeypatch.setenv('COPYLOT_VIEWER_MODE', str(int(mode == 'viewer')))
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    monkeypatch.setenv('COPYLOT_MAX_SESSIONS', '1')
    monkeypatch.setenv('COPYLOT_SESSION_IDLE_SECONDS', '60')
    monkeypatch.setattr(cleanup, '_LAST_SEEN', {})
    monkeypatch.setattr(tool_access, '_SESSION_AUTH', set())
    monkeypatch.setattr(viewer, '_SESSION_AUTH', {})
    monkeypatch.setattr(viewer, '_BOOTSTRAPPED_SESSION_PROJECT', {})
    monkeypatch.setattr(dataset_store, '_DATASET_SESSIONS', {})
    password_hash = hash_password('synthetic-password', iterations=100_000)
    token_hash = hashlib.sha256(b'synthetic-token').hexdigest()
    monkeypatch.setattr(tool_access, '_load_access', lambda *a: {
        'password_pbkdf2_sha256': password_hash, 'tokens': [token_hash],
    })
    monkeypatch.setattr(viewer, '_load_access_entries', lambda *a: [
        viewer.ViewerAccessEntry('synthetic', 'Synthetic', password_hash),
    ])
    monkeypatch.setattr(viewer, '_load_qr_access_entries', lambda *a: [
        viewer.ViewerQrAccessEntry('synthetic', 'Synthetic', token_hash),
    ])

    def load(*args, **kwargs):
        dataset_store.save_table_dataset('synthetic.csv', 'protein', pd.DataFrame({'ProteinNames': ['PRIVATE']}))

    monkeypatch.setattr(viewer, '_load_project_into_current_session', load)
    client = TestClient(app)
    prefix = f'/api/tabs/{tab}' if tab else ''
    path = f'{prefix}/api/{mode}/auth/{method}'
    payload = {'password': 'synthetic-password'} if method == 'login' else {'token': 'synthetic-token'}
    old = None
    for _ in range(2):
        response = client.post(path, json=payload)
        assert response.status_code == 200
        cookie_name = f'copylot_session_id_{tab}' if tab else 'copylot_session_id'
        current = _rotated_session_id(response, cookie_name)
        assert client.cookies.get(cookie_name) == current
        if tab:
            assert f'Path={prefix}' in response.headers['set-cookie']
            assert client.get('/api/tabs/' + 'b' * 32 + '/api/datasets/current').status_code == 401
            assert client.get('/api/datasets/current').status_code == 401
        assert set(cleanup._LAST_SEEN) == {current}
        if old:
            assert old != current
            assert old not in tool_access._SESSION_AUTH
            assert old not in viewer._SESSION_AUTH
            assert old not in dataset_store._DATASET_SESSIONS
        token = set_session_id(current)
        try:
            load()
        finally:
            reset_session_id(token)
        old = current
    cleanup._LAST_SEEN[current] -= 61
    assert client.get(prefix + '/api/datasets/current').status_code == 401
    assert current not in dataset_store._DATASET_SESSIONS
    assert current not in cleanup._LAST_SEEN

    if mode == 'viewer':
        def fail_after_loading(*args, **kwargs):
            load()
            raise RuntimeError('Synthetic initialization failure')
        monkeypatch.setattr(viewer, '_load_project_into_current_session', fail_after_loading)
        assert client.post(path, json=payload).status_code == 500
        assert not viewer._SESSION_AUTH
        assert not dataset_store._DATASET_SESSIONS
        assert not cleanup._LAST_SEEN


def test_ai_context_isolated_and_invalidated(monkeypatch, tmp_path):
    from app.services import dataset_store

    access_file = tmp_path / 'context-access.json'
    access_file.write_text(json.dumps({
        'password_pbkdf2_sha256': hash_password('synthetic-password', iterations=100_000),
        'tokens': [],
    }), encoding='utf-8')
    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_ENABLED', '1')
    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_FILE', str(access_file))
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    monkeypatch.setenv('COPYLOT_VIEWER_PORTAL_ENABLED', '0')
    monkeypatch.setattr('app.api.routes_chat.ai_mode_enabled', lambda: True)
    calls = []

    def evidence(request, cancelled=None):
        from app.schemas.assistant import AssistantResponse
        dataset = dataset_store.get_current_dataset('protein')
        marker = dataset.frame.iloc[0, 0] if dataset else 'EMPTY'
        calls.append(marker)
        return AssistantResponse(model="synthetic", answer=marker, revision=0)

    monkeypatch.setattr('app.api.routes_chat.assistant_step', evidence)

    def upload(client, marker):
        response = client.post('/api/datasets/upload', data={'kind': 'protein'}, files={
            'file': ('results.csv', f'ProteinNames,A1,A2\n{marker},12,13\n', 'text/csv'),
        })
        assert response.status_code == 200

    def context(client, marker):
        response = client.post('/api/chat/assistant', json={'message': 'Inspect', 'view': {'module': 'qc.coverage', 'workflow': 'protein'}})
        assert response.status_code == 200
        assert response.json()['answer'] == marker

    with TestClient(app) as first, TestClient(app) as second:
        for client in (first, second):
            assert client.post('/api/tool/auth/login', json={'password': 'synthetic-password'}).status_code == 200
        upload(first, 'FIRST_PRIVATE')
        upload(second, 'SECOND_PRIVATE')
        context(first, 'FIRST_PRIVATE')
        context(second, 'SECOND_PRIVATE')
        assert len(calls) == 2
        context(first, 'FIRST_PRIVATE')
        assert len(calls) == 3
        upload(first, 'REPLACED')
        context(first, 'REPLACED')
        assert first.post('/api/datasets/active', json={'packageName': 'Other'}).status_code == 200
        context(first, 'EMPTY')
        upload(first, 'OTHER_PACKAGE')
        context(first, 'OTHER_PACKAGE')
        assert first.post('/api/datasets/active', json={'packageName': 'Data'}).status_code == 200
        context(first, 'REPLACED')
        assert first.post('/api/tool/auth/logout').status_code == 200
        assert first.post('/api/chat/assistant', json={'message': 'Inspect', 'view': {'module': 'qc.coverage'}}).status_code == 401
        assert first.post('/api/tool/auth/login', json={'password': 'synthetic-password'}).status_code == 200
        context(first, 'EMPTY')


def test_authenticated_browsers_cannot_read_each_others_packages(monkeypatch, tmp_path):
    access_file = tmp_path / 'isolated-tool-access.json'
    access_file.write_text(json.dumps({
        'password_pbkdf2_sha256': hash_password('synthetic-password', iterations=100_000),
        'tokens': [],
    }), encoding='utf-8')
    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_ENABLED', '1')
    monkeypatch.setenv('COPYLOT_TOOL_ACCESS_FILE', str(access_file))
    monkeypatch.setenv('COPYLOT_SESSION_ISOLATION', '1')
    monkeypatch.setenv('COPYLOT_VIEWER_PORTAL_ENABLED', '0')
    with TestClient(app) as first, TestClient(app) as second:
        for client in (first, second):
            assert client.post('/api/tool/auth/login', json={'password': 'synthetic-password'}).status_code == 200
        assert first.cookies.get('copylot_session_id') != second.cookies.get('copylot_session_id')
        for client, name in ((first, 'First-private'), (second, 'Second-private')):
            assert client.post('/api/datasets/packages/create', json={'packageName': name}).status_code == 200
        uploaded = first.post('/api/datasets/upload', data={'kind': 'protein'}, files={
            'file': ('private.csv', 'ProteinNames,A1,A2\nPRIVATE_FEATURE,12,13\n', 'text/csv'),
        })
        assert uploaded.status_code == 200
        original = first.get('/api/datasets/current').json()
        assert 'First-private' in first.get('/api/datasets/current').json()['availablePackages']
        assert 'Second-private' not in first.get('/api/datasets/current').json()['availablePackages']
        assert 'First-private' not in second.get('/api/datasets/current').json()['availablePackages']
        # Tool mode permits creating an empty package by selecting a new name.
        # Reusing another session's name must not reuse its contents.
        selected = second.post('/api/datasets/active', json={'packageName': 'First-private'})
        assert selected.status_code == 200
        assert selected.json()['protein'] is None
        assert first.get('/api/datasets/current').json()['activePackage'] == 'First-private'
        assert first.get('/api/datasets/current').json() == original

@pytest.mark.parametrize("mode", ["tool", "viewer"])
def test_no_auth_response_carries_the_session_id_in_its_body(mode: str) -> None:
    """The cookie is HttpOnly; a copy in the JSON hands the same value away.

    The backend accepts a session id from the `X-CoPYlot-Session` header as well
    as from the cookie, so the id is a bearer token. Setting it HttpOnly and then
    echoing it in a readable body defeats the flag: an injected script, a library
    that logs responses or a proxy that records them all get a live authenticated
    session they can replay.

    Checked on the schema rather than by logging in, so it holds for every
    response those routes can produce, including the failure ones.
    """
    from app.schemas.tool_auth import ToolAuthLoginResponse, ToolAuthLogoutResponse
    from app.schemas.viewer_auth import ViewerAuthLoginResponse, ViewerAuthLogoutResponse

    models = (
        (ToolAuthLoginResponse, ToolAuthLogoutResponse)
        if mode == "tool"
        else (ViewerAuthLoginResponse, ViewerAuthLogoutResponse)
    )
    for model in models:
        fields = set(model.model_fields)
        leaking = {name for name in fields if "session" in name.lower()}
        assert not leaking, (
            f"{model.__name__} would return {sorted(leaking)} in its body; the "
            "rotated id belongs in Set-Cookie and nowhere else"
        )


@pytest.mark.parametrize("route,body", [
    ("/api/tool/auth/login", {"password": "header-client-password"}),
    ("/api/tool/auth/link-login", {"token": "header-client-token"}),
], ids=["password", "link"])
def test_the_rotated_id_is_still_reachable_by_a_header_based_client(monkeypatch, tmp_path, route, body) -> None:
    """Removing it from the body must not strand a non-browser client.

    A client that stores no cookies logs in, reads the new id from the
    `Set-Cookie` header of the login response -- the one channel left once the
    body stopped carrying it -- and sends it back in the session header. A login
    that rotates the id without handing it out leaves that client locked out.
    """
    import hashlib

    access_file = tmp_path / "tool_access.json"
    access_file.write_text(json.dumps({
        "password_pbkdf2_sha256": hash_password("header-client-password", iterations=100_000),
        "tokens": [hashlib.sha256(b"header-client-token").hexdigest()],
    }), encoding="utf-8")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_FILE", str(access_file))
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    monkeypatch.delenv("COPYLOT_VIEWER_PORTAL_ENABLED", raising=False)

    with TestClient(app) as client:
        client.cookies.clear()
        login = client.post(route, headers={"X-CoPYlot-Session": "before_login"}, json=body)
        assert login.status_code == 200, login.text
        rotated = _rotated_session_id(login)
        assert rotated != "before_login", "authentication must rotate the session id"

        client.cookies.clear()
        status = client.get("/api/tool/auth/status", headers={"X-CoPYlot-Session": rotated})
        assert status.json()["authenticated"] is True
        client.cookies.clear()
        assert client.get("/api/datasets/current", headers={"X-CoPYlot-Session": rotated}).status_code == 200

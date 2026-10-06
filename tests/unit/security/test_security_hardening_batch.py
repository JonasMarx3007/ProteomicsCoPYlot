"""Five small hardenings from the 2026-09 review, each with the failure it prevents.

1. Trusted proxies may be CIDR ranges, so the login limiter can see the real
   client behind a reverse proxy on the Docker bridge instead of keying every
   client on the gateway address (twelve wrong passwords from anyone locked
   everyone out); a successful login clears that client's count.
2. A local Ollama endpoint may only be Ollama's port with an /api/ path: the
   server calls it on the client's behalf, and "any port on localhost" reached
   every other local service.
3. Model names handed to `ollama pull`/`rm` are validated.
4. Upload directories and files under the system temp folder are private.
5. HSTS is sent behind TLS (directly, or via a trusted proxy's X-Forwarded-Proto).
"""

from __future__ import annotations

import os
import stat
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.main import app
from app.services import chat_tools, managed_temp, request_security


def _request(peer: str, forwarded: str | None = None, proto: str | None = None):
    headers = {}
    if forwarded is not None:
        headers["x-forwarded-for"] = forwarded
    if proto is not None:
        headers["x-forwarded-proto"] = proto
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=Headers(headers), url=SimpleNamespace(scheme="http"))


def test_a_cidr_trusted_proxy_range_reveals_the_forwarded_client(monkeypatch):
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "172.16.0.0/12, 10.1.2.3")
    assert request_security.client_address(_request("172.18.0.1", "203.0.113.9")) == "203.0.113.9"
    assert request_security.client_address(_request("10.1.2.3", "203.0.113.9")) == "203.0.113.9"
    # Not a trusted peer: the header is ignored.
    assert request_security.client_address(_request("192.168.5.5", "203.0.113.9")) == "192.168.5.5"
    # Trusted peer, garbage header: falls back to the peer.
    assert request_security.client_address(_request("172.18.0.1", "not-an-ip")) == "172.18.0.1"


def test_an_empty_or_invalid_trusted_list_trusts_nobody(monkeypatch):
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "")
    assert request_security.client_address(_request("172.18.0.1", "203.0.113.9")) == "172.18.0.1"
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "not/a/network")
    assert request_security.client_address(_request("172.18.0.1", "203.0.113.9")) == "172.18.0.1"


@pytest.mark.parametrize("chain", [
    "127.0.0.1, 203.0.113.9",
    "127.0.0.1, 203.0.113.9, 172.18.0.2",
    "spoofed, 203.0.113.9",
])
def test_forwarded_chain_cannot_spoof_client_or_local_access(monkeypatch, chain):
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    request = _request("172.18.0.1", chain)
    assert request_security.client_address(request) == "203.0.113.9"
    assert not request_security.local_path_access_allowed(request)


def test_multiple_forwarded_headers_are_one_chain(monkeypatch):
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    request = _request("172.18.0.1")
    request.headers = Headers(raw=[
        (b"x-forwarded-for", b"127.0.0.1"),
        (b"x-forwarded-for", b"203.0.113.9, 172.18.0.2"),
    ])
    assert request_security.client_address(request) == "203.0.113.9"


def test_malformed_nearest_forwarded_hop_does_not_trust_earlier_entries(monkeypatch):
    monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "172.16.0.0/12")
    assert request_security.client_address(_request("172.18.0.1", "127.0.0.1, invalid")) == "172.18.0.1"


def test_a_successful_login_clears_the_failed_attempts_for_that_client(monkeypatch):
    from app.api.routes_tool_auth import LOGIN_RATE_LIMIT as limiter

    monkeypatch.setenv("COPYLOT_TOOL_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "3")
    limiter.attempts.clear()
    request = _request("203.0.113.9")
    for _ in range(3):
        limiter.enforce(request, bucket="password")
    with pytest.raises(Exception):
        limiter.enforce(request, bucket="password")
    limiter.clear(request, bucket="password")
    limiter.enforce(request, bucket="password")  # allowed again
    # Another client's count is untouched by the first client's success.
    other = _request("198.51.100.4")
    for _ in range(3):
        limiter.enforce(other, bucket="password")
    limiter.clear(request, bucket="password")
    with pytest.raises(Exception):
        limiter.enforce(other, bucket="password")
    limiter.attempts.clear()


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:11434", "localhost:11434/api/chat", "http://[::1]:11434/api/generate"])
def test_local_ollama_endpoints_on_the_ollama_port_are_accepted(monkeypatch, endpoint):
    monkeypatch.delenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", raising=False)
    monkeypatch.delenv("COPYLOT_OLLAMA_URL", raising=False)
    assert chat_tools._normalize_ollama_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", ["http://127.0.0.1:8080", "http://localhost:5432", "http://localhost", "https://localhost/api/chat", "http://127.0.0.1:0/api/chat", "http://127.0.0.1:11434/admin", "http://127.0.0.1:11434/v1/models"])
def test_other_local_ports_and_paths_are_refused(monkeypatch, endpoint):
    monkeypatch.delenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", raising=False)
    monkeypatch.delenv("COPYLOT_OLLAMA_URL", raising=False)
    with pytest.raises(ValueError):
        chat_tools._normalize_ollama_endpoint(endpoint)


def test_an_explicitly_allowed_origin_may_use_any_port(monkeypatch):
    monkeypatch.setenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", "http://127.0.0.1:8080")
    assert chat_tools._normalize_ollama_endpoint("http://127.0.0.1:8080/api/chat")


@pytest.mark.parametrize("name", ["llama3.1:8b", "mistral", "library/gemma2:latest", "hf.co/user/repo:Q4_K_M"])
def test_model_names_ollama_accepts_pass(name):
    assert chat_tools._validated_model_name(name) == name


@pytest.mark.parametrize("name", ["", "-rf", "--insecure", "a b", "x;rm", "../x", ":tag", "a:b:c", "a\nb"])
def test_model_names_that_are_not_names_are_refused(name):
    with pytest.raises(ValueError):
        chat_tools._validated_model_name(name)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_managed_temp_directories_and_files_are_private(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_temp.tempfile, "gettempdir", lambda: str(tmp_path))
    directory = managed_temp.private_temp_dir("table_uploads")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(directory.parent.stat().st_mode) == 0o700
    target = directory / "upload.tsv"
    managed_temp.write_private_bytes(target, b"a\tb\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with managed_temp.open_private(target, "w") as handle:
        handle.write("x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600 and target.read_text() == "x"


def test_private_text_tables_are_utf8_on_every_platform(tmp_path):
    target = tmp_path / "derived.tsv"
    text = "Protein\tCondition\nβ-catenin\t刺激\n"
    with managed_temp.open_private(target, "w") as handle:
        assert handle.encoding.lower().replace("-", "") == "utf8"
        handle.write(text)
    assert target.read_bytes() == text.encode("utf-8")


@pytest.mark.parametrize("name", ["..", "../outside", "", "."])
def test_managed_temp_directory_cannot_escape_its_root(tmp_path, monkeypatch, name):
    monkeypatch.setattr(managed_temp.tempfile, "gettempdir", lambda: str(tmp_path))
    with pytest.raises(ValueError):
        managed_temp.private_temp_dir(name)


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks and permissions")
def test_managed_temp_rejects_a_symlink_root(tmp_path, monkeypatch):
    monkeypatch.setattr(managed_temp.tempfile, "gettempdir", lambda: str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "ProteomicsCoPYlot").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        managed_temp.private_temp_dir("table_uploads")
    assert not list(outside.iterdir())


def test_transport_security_header_only_over_tls(monkeypatch):
    with TestClient(app, base_url="http://localhost") as client:
        plain = client.get("/api/datasets/current")
        assert "Strict-Transport-Security" not in plain.headers
        # Behind a trusted proxy that terminated TLS.
        monkeypatch.setenv("COPYLOT_TRUSTED_PROXY_IPS", "testclient")
        assert "Strict-Transport-Security" not in client.get("/api/datasets/current").headers
    with TestClient(app, base_url="https://localhost") as client:
        secure = client.get("/api/datasets/current")
        assert secure.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"

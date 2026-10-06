from __future__ import annotations

import io
import logging
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]

from app.main import app
from app.schemas.chat import ChatRequest
from app.services.chat_tools import _resolve_api_key

ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
SECRET = "synthetic-browser-api-key-for-redaction-test"


def test_only_replacement_assistant_contract_is_exposed():
    from app.schemas.assistant import AssistantRequest

    schema = app.openapi()
    paths = set(schema["paths"])
    assert "/api/chat/assistant" in paths
    assert not paths.intersection({
        "/api/chat/ollama", "/api/chat/ollama-stream",
        "/api/chat/stream", "/api/chat/module-context",
    })
    assert not {"temperature", "maxTokens", "analysisContext"}.intersection(AssistantRequest.model_fields)
    assert not {"OllamaChatResponse", "ModuleContextRequest", "ModuleContextResponse"}.intersection(
        schema["components"]["schemas"]
    )


def _request(provider: str, key: str | None = None) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": "hello"}],
        provider=provider,
        apiKey=key,
    )


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch):
    for name in ENV_NAMES.values():
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("provider", sorted(ENV_NAMES))
def test_server_key_takes_precedence_over_browser_key(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_NAMES[provider], "from-server")
    assert _resolve_api_key(_request(provider, "from-browser"), provider) == "from-server"


@pytest.mark.parametrize("provider", sorted(ENV_NAMES))
def test_browser_key_is_still_accepted_when_the_server_has_none(provider: str) -> None:
    assert _resolve_api_key(_request(provider, "from-browser"), provider) == "from-browser"


@pytest.mark.parametrize("provider", sorted(ENV_NAMES))
def test_server_key_alone_is_enough(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_NAMES[provider], "from-server")
    assert _resolve_api_key(_request(provider), provider) == "from-server"


@pytest.mark.parametrize("provider", sorted(ENV_NAMES))
def test_missing_key_names_the_environment_variable(provider: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        _resolve_api_key(_request(provider), provider)
    assert ENV_NAMES[provider] in str(excinfo.value)


def test_ollama_requires_no_key() -> None:
    assert _resolve_api_key(_request("ollama", "ignored"), "ollama") == ""


@pytest.mark.parametrize('provider', sorted(ENV_NAMES))
def test_cloud_route_accepts_server_key_only_after_consent(provider, monkeypatch):
    from app.services import chat_tools

    monkeypatch.setenv('COPYLOT_AI_MODE', '1')
    monkeypatch.setenv(ENV_NAMES[provider], SECRET)
    calls = []

    def reply(**kwargs):
        calls.append(kwargs)
        assert kwargs['api_key'] == SECRET
        assert SECRET not in str(kwargs['messages'])
        return '{"task":"clarify","clarification":"request"}'

    monkeypatch.setattr(chat_tools, f'_{provider}_chat_text', reply)
    with TestClient(app) as client:
        payload = {'provider': provider, 'message': 'Hello', 'model': 'synthetic-model', 'view': {'module': 'data.upload'}}
        assert client.post('/api/chat/assistant', json=payload).status_code == 428
        assert calls == []
        status = client.get(f'/api/chat/cloud-consent/{provider}').json()
        assert client.post(f'/api/chat/cloud-consent/{provider}/grant', json={
            'disclosureVersion': status['disclosureVersion'],
        }).status_code == 200
        response = client.post('/api/chat/assistant', json=payload)
        assert response.status_code == 200
        assert response.json()["answer"] == "Which plot or selection would you like me to use?"
        monkeypatch.delenv(ENV_NAMES[provider])
        missing = client.post('/api/chat/assistant', json=payload)
        assert missing.status_code == 400
        assert ENV_NAMES[provider] in missing.text
        assert SECRET not in missing.text
        assert len(calls) == 1


def test_key_is_not_echoed_by_validation_errors_or_logs() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            malformed = client.post(
                "/api/chat/assistant",
                json={"provider": "openai", "apiKey": SECRET, "messages": "not-a-list"},
            )
            failing = client.post(
                "/api/chat/assistant",
                json={
                    "provider": "openai",
                    "apiKey": SECRET,
                    "messages": [{"role": "user", "content": "hi"}],
                    "model": "gpt-4o-mini",
                },
            )
    finally:
        root.removeHandler(handler)

    assert SECRET not in malformed.text
    assert SECRET not in failing.text
    assert SECRET not in stream.getvalue()


@pytest.mark.parametrize("provider", sorted(ENV_NAMES))
def test_upstream_error_cannot_echo_server_key(provider, monkeypatch, caplog):
    from app.services import chat_tools

    monkeypatch.setenv("COPYLOT_AI_MODE", "1")
    monkeypatch.setenv(ENV_NAMES[provider], SECRET)
    bodies = []

    def fail(request, **kwargs):
        assert SECRET in str(request.headers)
        body = io.BytesIO(f"Rejected credential: {SECRET}".encode())
        bodies.append(body)
        raise urllib.error.HTTPError(request.full_url, 401, SECRET, {}, body)

    monkeypatch.setattr(chat_tools._PROVIDER_OPENER, "open", fail)
    with TestClient(app) as client:
        status = client.get(f"/api/chat/cloud-consent/{provider}").json()
        assert client.post(f"/api/chat/cloud-consent/{provider}/grant", json={
            "disclosureVersion": status["disclosureVersion"],
        }).status_code == 200
        response = client.post("/api/chat/assistant", json={
            "provider": provider, "message": "Hello", "model": "synthetic-model", "view": {"module": "data.upload"},
        })
    assert response.status_code == 400
    assert "HTTP 401" in response.text
    assert SECRET not in response.text
    assert SECRET not in caplog.text
    assert len(bodies) == 1 and bodies[0].closed

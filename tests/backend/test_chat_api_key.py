from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app
from app.schemas.chat import OllamaChatRequest
from app.services.chat_tools import _resolve_api_key

ENV_NAMES = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
SECRET = "synthetic-browser-api-key-for-redaction-test"


def _request(provider: str, key: str | None = None) -> OllamaChatRequest:
    return OllamaChatRequest(
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


def test_key_is_not_echoed_by_validation_errors_or_logs() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            malformed = client.post(
                "/api/chat/ollama",
                json={"provider": "openai", "apiKey": SECRET, "messages": "not-a-list"},
            )
            failing = client.post(
                "/api/chat/ollama",
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

"""One list of cloud default models, on the server.

The browser pre-filled `claude-3-5-sonnet-latest` and `gemini-2.0-flash` (shut
down on 2026-06-01) while the backend defaulted to other models. The backend
now keeps the only list, serves it to the browser, and lets an administrator
override each entry with an environment variable. That the browser uses the
served list and keeps none of its own is tested in
frontend/tests/unit/provider-default-models.test.tsx.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.chat import ChatRequest
from app.services import chat_tools


def test_defaults_are_current_and_complete():
    assert chat_tools.provider_default_models() == {
        "openai": "gpt-5.4-mini", "anthropic": "claude-sonnet-5-5", "gemini": "gemini-3.8-flash"}


def test_an_environment_override_replaces_one_entry(monkeypatch):
    monkeypatch.setenv("COPYLOT_DEFAULT_GEMINI_MODEL", "gemini-3.5-flash-lite")
    assert chat_tools.provider_default_models()["gemini"] == "gemini-3.5-flash-lite"
    assert chat_tools.provider_default_models()["openai"] == "gpt-5.4-mini"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_an_empty_model_name_resolves_to_the_default(provider):
    payload = ChatRequest(message="x", provider=provider)
    assert chat_tools._resolve_chat_model(payload, provider) == chat_tools.provider_default_models()[provider]


def test_the_route_serves_the_list_in_ai_mode(monkeypatch):
    monkeypatch.setenv("COPYLOT_AI_MODE", "1")
    with TestClient(app) as client:
        response = client.get("/api/chat/provider-defaults")
    assert response.status_code == 200
    assert response.json() == {"models": chat_tools.provider_default_models()}


def test_the_route_is_absent_without_ai_mode(monkeypatch):
    monkeypatch.setenv("COPYLOT_AI_MODE", "0")
    with TestClient(app) as client:
        assert client.get("/api/chat/provider-defaults").status_code == 404

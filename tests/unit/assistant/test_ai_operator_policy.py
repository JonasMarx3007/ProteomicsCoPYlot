"""The server operator decides which AI providers and models a deployment may use."""
from __future__ import annotations

import pytest

from app.services import chat_tools


def test_everything_is_allowed_by_default(monkeypatch):
    for name in ("COPYLOT_AI_ALLOWED_PROVIDERS", "COPYLOT_AI_ALLOWED_MODELS"):
        monkeypatch.delenv(name, raising=False)
    assert chat_tools.allowed_ai_providers() == ["ollama", "openai_compatible", "openai", "anthropic", "gemini"]
    chat_tools.check_ai_operator_policy("openai", "any-model")


def test_providers_and_models_can_be_restricted(monkeypatch):
    monkeypatch.setenv("COPYLOT_AI_ALLOWED_PROVIDERS", "ollama, anthropic")
    monkeypatch.setenv("COPYLOT_AI_ALLOWED_MODELS", "anthropic:claude-small, anthropic:claude-large")
    chat_tools.check_ai_operator_policy("ollama", "llama3")
    chat_tools.check_ai_operator_policy("anthropic", "claude-small")
    with pytest.raises(ValueError, match="does not allow the AI provider 'openai'"):
        chat_tools.check_ai_operator_policy("openai", "gpt")
    with pytest.raises(ValueError, match="does not allow the model 'claude-other'"):
        chat_tools.check_ai_operator_policy("anthropic", "claude-other")


def test_the_completion_refuses_before_anything_is_sent(monkeypatch):
    from app.schemas.chat import ChatRequest

    monkeypatch.setenv("COPYLOT_AI_ALLOWED_PROVIDERS", "ollama")
    monkeypatch.setattr(chat_tools, "require_cloud_ai_consent", lambda provider: None)
    sent = []
    monkeypatch.setattr(chat_tools, "_openai_chat_text", lambda **kwargs: sent.append(kwargs) or "x")
    payload = ChatRequest(message="hi", provider="openai", model="gpt-test")
    with pytest.raises(ValueError, match="does not allow"):
        chat_tools.assistant_completion(payload, "instruction", "data")
    assert not sent


@pytest.mark.parametrize("env,expected", [
    ({}, True),
    ({"COPYLOT_TOOL_ACCESS_ENABLED": "1"}, False),
    ({"COPYLOT_VIEWER_PORTAL_ENABLED": "1"}, False),
    ({"COPYLOT_TOOL_ACCESS_ENABLED": "1", "COPYLOT_OLLAMA_MODEL_MANAGEMENT": "1"}, True),
    ({"COPYLOT_OLLAMA_MODEL_MANAGEMENT": "0"}, False),
])
def test_model_management_is_for_the_operator_on_deployments(monkeypatch, env, expected):
    for name in ("COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED",
                 "COPYLOT_OLLAMA_MODEL_MANAGEMENT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert chat_tools.ollama_model_management_allowed() is expected


def test_install_route_refuses_when_management_is_reserved(client, monkeypatch):
    monkeypatch.setenv("COPYLOT_AI_MODE", "1")
    monkeypatch.setenv("COPYLOT_OLLAMA_MODEL_MANAGEMENT", "0")
    response = client.post("/api/chat/models/install", json={"model": "llama3"})
    assert response.status_code == 403
    defaults = client.get("/api/chat/provider-defaults").json()
    assert defaults["policy"]["modelManagement"] is False

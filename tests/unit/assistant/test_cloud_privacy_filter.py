"""Nothing that looks like a local path or a credential is sent to a cloud provider.

The consent text promises that local filesystem paths are excluded. The filter
only knew Windows paths, so `/home/<user>/...` and `/Users/<user>/...` passed,
and it checked the data message but not the instruction sent with it. It also
had no tests: deleting it left every assistant test passing.
"""
from __future__ import annotations

import pytest

from app.schemas.chat import ChatRequest
from app.services import chat_tools


@pytest.mark.parametrize("text", [
    r"file=C:\Users\jonas\data\run1.raw",
    "source \\\\server\\share\\report.tsv",
    "open file:///tmp/x.csv",
    "path=/home/jonas/projects/hek293.tsv",
    "loaded from /Users/jonas/Desktop/run.d",
    "see ~/Documents/report.tsv",
    "cache in /tmp/copylot/abc",
    "mounted at /Volumes/Data/run.raw",
    "api_key: sk-123",
    "Authorization= Bearer abc",
    "-----BEGIN RSA PRIVATE KEY-----",
])
def test_protected_values_are_refused(text):
    with pytest.raises(ValueError, match="protected path or credential-like value"):
        chat_tools._validate_cloud_analysis_context(f"context line\n{text}\nmore")


@pytest.mark.parametrize("text", [
    "GET /api/plots/stats/protein/volcano.png",
    "condition=GRK/WT|ratio=1/2",
    "entity=proteins|log2FC=mean(GRK)-mean(WT)",
    "the home directory of the kinase family",
    "users asked for 2D and 3D plots",
])
def test_ordinary_analysis_context_passes(text):
    assert chat_tools._validate_cloud_analysis_context(text) == text


@pytest.fixture
def cloud(monkeypatch):
    sent = []
    monkeypatch.setattr(chat_tools, "require_cloud_ai_consent", lambda provider: None)
    monkeypatch.setattr(chat_tools, "_resolve_chat_model", lambda payload, provider: "model")
    monkeypatch.setattr(chat_tools, "_resolve_api_key", lambda payload, provider: "key")
    monkeypatch.setattr(chat_tools, "_openai_chat_text", lambda **kwargs: sent.append(kwargs) or "ok")
    return sent


def test_a_path_in_the_data_stops_the_request_before_sending(cloud):
    payload = ChatRequest(message="explain", provider="openai")
    with pytest.raises(ValueError, match="protected path"):
        chat_tools.assistant_completion(payload, "Explain the plot.", "sample=/home/jonas/run1.raw")
    assert cloud == []


def test_a_path_in_the_instruction_stops_the_request_before_sending(cloud):
    payload = ChatRequest(message="explain", provider="openai")
    with pytest.raises(ValueError, match="protected path"):
        chat_tools.assistant_completion(payload, "Dataset loaded from /Users/jonas/run.tsv.", "condition=A")
    assert cloud == []


def test_clean_context_is_sent(cloud):
    payload = ChatRequest(message="explain", provider="openai")
    assert chat_tools.assistant_completion(payload, "Explain the plot.", "condition=A") == ("model", "ok")
    assert len(cloud) == 1


def test_local_ollama_is_not_filtered(monkeypatch):
    """The filter guards what leaves the machine; a local model sees the same context unfiltered."""
    called = []
    monkeypatch.setattr(chat_tools, "_validate_cloud_analysis_context", lambda value: called.append(value))
    monkeypatch.setattr(chat_tools, "_resolve_model", lambda *args: "llama")
    monkeypatch.setattr(chat_tools, "_ollama_num_ctx", lambda *args: 8192)

    class _Response:
        pass

    monkeypatch.setattr(chat_tools, "_open_ollama_request", lambda *args, **kwargs: ("llama", _Response()))
    monkeypatch.setattr(chat_tools, "read_json_response", lambda response, message: {"message": {"content": "ok"}})
    chat_tools.assistant_completion(ChatRequest(message="x", provider="ollama"), "Instruction.", "/home/jonas/x")
    assert called == []

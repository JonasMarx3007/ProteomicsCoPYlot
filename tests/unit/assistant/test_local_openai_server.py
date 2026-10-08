"""A local server that speaks the OpenAI-compatible API (llama.cpp, vLLM, LM Studio).

The stand-in below answers like llama.cpp's server: `/v1/models`,
`/v1/chat/completions` and `/props`, and 404 on Ollama's `/api/tags` and
`/api/chat` -- the situation that made an Ollama endpoint useless for it.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.schemas.chat import ChatRequest
from app.services import chat_tools, local_ai_server

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


class LlamaCppStandIn:
    def __init__(self):
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.mode = "ok"  # ok | reject_schema | context | length | auth
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                stand_in.headers.append(dict(self.headers))
                if self.path == "/v1/models":
                    self._send(200, {"object": "list", "data": [
                        {"id": "glm5", "object": "model", "owned_by": "llamacpp",
                         "meta": {"n_params": 320759404382, "n_ctx_train": 1048576}},
                        {"id": "nomic-embed-text", "object": "model", "owned_by": "llamacpp"}],
                        "models": [{"name": "glm5", "model": "glm5", "capabilities": ["completion", "multimodal"]}]})
                elif self.path == "/props":
                    self._send(200, {"default_generation_settings": {"n_ctx": 16384}, "modalities": {"vision": True},
                                     "chat_template_caps": {"supports_reasoning_effort": True}})
                else:
                    self._send(404, {"error": {"code": 404, "message": "File Not Found"}})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                stand_in.headers.append(dict(self.headers))
                if self.path != "/v1/chat/completions":
                    self._send(404, {"error": {"code": 404, "message": "File Not Found"}})
                    return
                stand_in.requests.append(body)
                if stand_in.mode == "auth":
                    self._send(401, {"error": {"message": "Invalid API Key"}})
                elif stand_in.mode == "context":
                    self._send(400, {"error": {"message": "the request exceeds the available context size"}})
                elif stand_in.mode == "reject_schema" and "response_format" in body:
                    self._send(400, {"error": {"message": "response_format type json_schema is not supported"}})
                elif body.get("stream"):
                    # llama.cpp's server-sent events: thinking, then the answer or a tool call.
                    events = [{"choices": [{"delta": {"reasoning_content": "hm"}}]}] * 3
                    if body.get("tools"):
                        events.append({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
                            "name": "apply_styles", "arguments": '{"styles": '}}]}}]})
                        events.append({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                            "arguments": '[]}'}}]}, "finish_reason": "tool_calls"}]})
                    else:
                        events.append({"choices": [{"delta": {"content": '{"answer": '}}]})
                        events.append({"choices": [{"delta": {"content": '"fine"}'}, "finish_reason": "stop"}]})
                    events.append({"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 9, "total_tokens": 59}})
                    data = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
                    payload = data.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    finish = "length" if stand_in.mode == "length" else "stop"
                    self._send(200, {
                        "object": "chat.completion",
                        "model": body.get("model"),
                        "choices": [{"index": 0, "finish_reason": finish,
                                     "message": {"role": "assistant", "content": '{"answer": "fine"}'}}],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 8, "total_tokens": 58},
                    })

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def server(monkeypatch):
    for name in ("COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED",
                 "COPYLOT_LOCAL_AI_URL", "COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS", "COPYLOT_LOCAL_AI_API_KEY",
                 "COPYLOT_LOCAL_AI_MODEL", "COPYLOT_LOCAL_AI_CONTEXT_TOKENS", "COPYLOT_AI_ALLOWED_PROVIDERS",
                 "COPYLOT_AI_ALLOWED_MODELS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    stand_in = LlamaCppStandIn()
    yield stand_in
    stand_in.close()


def _request(server, **changes) -> ChatRequest:
    values = {"message": "hello", "provider": "openai_compatible", "model": "glm5", "localServerUrl": server.url}
    values.update(changes)
    return ChatRequest(**values)


def test_the_models_come_from_v1_models_without_embedding_models(server):
    listed = local_ai_server.server_models(server.url)
    assert listed.models == ["glm5"] and listed.selectedModel == "glm5" and listed.warnings == []


@pytest.mark.parametrize("typed", ["{url}", "{url}/", "{url}/chat/completions", "{url}/models", "{root}"])
def test_any_usual_spelling_of_the_address_resolves_to_the_v1_base(server, typed):
    root = server.url[: -len("/v1")]
    assert local_ai_server.resolve_base_url(typed.format(url=server.url, root=root)) == server.url


def test_the_assistant_gets_an_answer_and_sends_the_schema(server):
    model, text = chat_tools.assistant_completion(_request(server), "system", "data", schema=SCHEMA)
    assert (model, text) == ("glm5", '{"answer": "fine"}')
    sent = server.requests[-1]
    assert sent["model"] == "glm5" and sent["temperature"] == 0 and sent["stream"] is False
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert [message["role"] for message in sent["messages"]] == ["system", "user"]


def test_a_server_without_structured_output_is_asked_again_without_it(server):
    server.mode = "reject_schema"
    _, text = chat_tools.assistant_completion(_request(server), "system", "data", schema=SCHEMA)
    assert text == '{"answer": "fine"}'
    assert "response_format" in server.requests[0] and "response_format" not in server.requests[1]


def test_a_full_context_window_is_reported_as_such(server):
    server.mode = "context"
    with pytest.raises(chat_tools.AssistantContextExhausted, match="16384-token context window"):
        chat_tools.assistant_completion(_request(server), "system", "data", schema=SCHEMA)


def test_a_prompt_larger_than_the_window_is_refused_before_sending(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_LOCAL_AI_CONTEXT_TOKENS", "2048")
    with pytest.raises(chat_tools.AssistantContextExhausted, match="context is 2048"):
        chat_tools.assistant_completion(_request(server), "system", "x" * 6000)
    assert server.requests == []


def test_a_cut_off_answer_is_not_used(server):
    server.mode = "length"
    with pytest.raises(ValueError, match="whole reply budget"):
        chat_tools.assistant_completion(_request(server), "system", "data")


def test_a_refused_key_is_named(server):
    server.mode = "auth"
    with pytest.raises(ValueError, match="API key"):
        chat_tools.assistant_completion(_request(server, apiKey="wrong"), "system", "data")


def test_the_server_key_wins_over_a_typed_one(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_LOCAL_AI_API_KEY", "server-key")
    monkeypatch.setenv("COPYLOT_LOCAL_AI_URL", server.url)
    chat_tools.assistant_completion(_request(server, apiKey="typed-key"), "system", "data")
    assert server.headers[-1].get("Authorization") == "Bearer server-key"


def test_a_stored_key_cannot_be_sent_to_an_unconfigured_desktop_endpoint(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_LOCAL_AI_API_KEY", "server-key")
    monkeypatch.setenv("COPYLOT_LOCAL_AI_URL", "https://approved.example/v1")
    response = local_ai_server.server_models(server.url)
    assert response.models == [] and response.warnings
    with pytest.raises(ValueError, match="COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS"):
        local_ai_server.chat_message(_request(server), [], model="glm5", schema=None, context_window=8192)
    assert server.headers == []


def test_https_allowlist_guidance_keeps_the_requested_scheme(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    with pytest.raises(ValueError, match="add https://private.example:8443 to"):
        local_ai_server.resolve_base_url("https://private.example:8443/v1")


def test_it_is_trusted_like_ollama_no_consent_and_full_context(server):
    # A path in the context is held back from cloud providers; a local server gets it.
    model, _ = chat_tools.assistant_completion(_request(server), "system", "file at /home/lab/run1.raw")
    assert model == "glm5"
    from app.services.cloud_ai_consent import cloud_ai_consent_status

    status = cloud_ai_consent_status("openai_compatible")
    assert status.required is False and status.granted is True


def test_the_context_window_comes_from_props_and_sets_the_prompt_budget(server):
    assert local_ai_server.context_tokens(server.url) == 16384
    preferred, maximum = chat_tools.assistant_prompt_budget(_request(server))
    # glm5 thinks before answering: its reply budget grows, within a third of the window.
    reserve = chat_tools.assistant_output_reserve(_request(server))
    assert preferred == maximum == 16384 - reserve and 16384 // 3 + 128 >= reserve > chat_tools.ASSISTANT_OUTPUT_RESERVE
    capability = chat_tools.model_capability("openai_compatible", "glm5", server.url)
    assert capability.contextWindow == 16384 and capability.provider == "openai_compatible"


def test_the_operator_policy_applies(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_AI_ALLOWED_PROVIDERS", "ollama")
    with pytest.raises(ValueError, match="does not allow the AI provider"):
        chat_tools.assistant_completion(_request(server), "system", "data")
    monkeypatch.setenv("COPYLOT_AI_ALLOWED_PROVIDERS", "ollama,openai_compatible")
    monkeypatch.setenv("COPYLOT_AI_ALLOWED_MODELS", "openai_compatible:other")
    with pytest.raises(ValueError, match="does not allow the model 'glm5'"):
        chat_tools.assistant_completion(_request(server), "system", "data")


def test_a_deployment_only_reaches_servers_the_operator_listed(server, monkeypatch):
    monkeypatch.setenv("COPYLOT_TOOL_ACCESS_ENABLED", "1")
    with pytest.raises(ValueError, match="COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS"):
        local_ai_server.resolve_base_url(server.url)
    monkeypatch.setenv("COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS", server.url[: -len("/v1")])
    assert local_ai_server.resolve_base_url(server.url) == server.url


def test_a_desktop_run_uses_the_address_its_user_enters(server):
    # The person at the keyboard is the operator: no environment setting needed.
    assert local_ai_server.resolve_base_url("http://10.0.0.5:8084/v1") == "http://10.0.0.5:8084/v1"


@pytest.mark.parametrize("flag", ["COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED"])
def test_a_deployment_reaches_only_listed_remote_servers(server, monkeypatch, flag):
    monkeypatch.setenv(flag, "1")
    with pytest.raises(ValueError, match="add http://10.0.0.5:8084 to COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS"):
        local_ai_server.resolve_base_url("http://10.0.0.5:8084/v1")
    monkeypatch.setenv("COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS", "http://10.0.0.5:8084")
    assert local_ai_server.resolve_base_url("http://10.0.0.5:8084/v1") == "http://10.0.0.5:8084/v1"
    with pytest.raises(ValueError, match="only reaches"):
        local_ai_server.resolve_base_url("http://10.0.0.5:9999/v1")


@pytest.mark.parametrize("bad", ["ftp://127.0.0.1/v1", "http://user:pw@127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1?x=1"])
def test_unsafe_addresses_are_refused(server, bad):
    with pytest.raises(ValueError):
        local_ai_server.resolve_base_url(bad)


def test_the_routes_list_models_and_report_the_preset(server, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("COPYLOT_AI_MODE", "1")
    monkeypatch.setenv("COPYLOT_LOCAL_AI_URL", server.url)
    with TestClient(app) as client:
        listed = client.post("/api/chat/local-models", json={"endpoint": server.url})
        assert listed.status_code == 200 and listed.json()["models"] == ["glm5"]
        defaults = client.get("/api/chat/provider-defaults").json()
        assert defaults["localServerUrl"] == server.url
        assert "openai_compatible" in defaults["policy"]["providers"]


def test_the_server_describes_its_model_and_glm5_is_advanced(server):
    capability = chat_tools.model_capability("openai_compatible", "glm5", server.url)
    assert capability.parameterCountB == 320.76 and capability.source == "metadata"
    assert capability.supportsVision is True and capability.reasoning is True
    assert capability.contextTier == "extended" and capability.levelName == "Advanced" and capability.assessment == "observed"
    # Room to think: more than the old fixed 1,024 tokens, within a third of the window.
    assert 1024 < capability.outputTokens <= 16384 // 3


def test_the_reply_budget_and_the_plot_image_reach_the_server(server):
    image = "data:image/png;base64,iVBORw0KGgo="
    chat_tools.assistant_completion(_request(server), "system", "data", schema=SCHEMA, image=image)
    sent = server.requests[-1]
    assert sent["max_tokens"] > 1024
    content = sent["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "data"} and content[1]["image_url"]["url"] == image


def test_the_level_the_user_chooses_sets_the_budget(server):
    chat_tools.assistant_completion(_request(server, assistantLevel="basic"), "system", "data")
    assert server.requests[-1]["max_tokens"] == 1024 + 3072  # Basic, but glm5 still needs room to think


def test_a_streamed_reply_reports_progress_and_reads_the_same(server):
    from app.schemas.assistant import AssistantRequest
    from app.services import assistant_progress

    request = AssistantRequest(message="hello there friend", provider="openai_compatible", model="glm5",
                               localServerUrl=server.url, view={"module": "qc.cv"}, progressId="progress-0001")
    _, text = chat_tools.assistant_completion(request, "system", "data", schema=SCHEMA)
    assert text == '{"answer": "fine"}' and server.requests[-1]["stream"] is True
    state = assistant_progress.read("progress-0001")
    assert state["phase"] == "answering" and state["tokens"] >= 5 and state["calls"] == 1


def test_the_reasoning_effort_is_sent_only_where_the_template_takes_it(server, monkeypatch):
    chat_tools.assistant_completion(_request(server), "system", "data")
    assert "reasoning_effort" not in server.requests[-1]
    from app.services import local_ai_server

    local_ai_server.chat_text(_request(server), [{"role": "user", "content": "x"}], model="glm5", schema=None,
                              context_window=16384, effort="high")
    assert server.requests[-1]["reasoning_effort"] == "high"
    monkeypatch.setenv("COPYLOT_LOCAL_AI_REASONING_EFFORT", "server")
    local_ai_server.chat_text(_request(server), [{"role": "user", "content": "x"}], model="glm5", schema=None,
                              context_window=16384, effort="high")
    assert "reasoning_effort" not in server.requests[-1]


def test_native_tool_calls_arrive_assembled(server):
    from app.schemas.assistant import AssistantRequest

    assert chat_tools.native_tools_supported(_request(server)) is False  # the stand-in template reports no tools
    request = AssistantRequest(message="make it nice", provider="openai_compatible", model="glm5",
                               localServerUrl=server.url, view={"module": "qc.cv"}, progressId="progress-0002")
    tools = [{"type": "function", "function": {"name": "apply_styles", "parameters": {"type": "object"}}}]
    _, message = chat_tools.assistant_tool_turn(request, [{"role": "user", "content": "x"}], tools)
    call = message["tool_calls"][0]
    assert call["function"]["name"] == "apply_styles" and json.loads(call["function"]["arguments"]) == {"styles": []}
    assert server.requests[-1]["tool_choice"] == "required"

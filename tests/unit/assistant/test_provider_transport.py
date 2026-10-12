import io
import json
import urllib.error
import urllib.request
import urllib.response
from email.message import Message

import pytest

from app.services import chat_tools, provider_http


@pytest.mark.parametrize("stage", ["headers", "stall", "trickle", "success"])
def test_actual_http_deadline_interrupts_slow_provider(stage):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                if stage == "headers":
                    time.sleep(0.7)
                self.send_response(200)
                self.end_headers()
                if stage == "success":
                    self.wfile.write(b"ok")
                    return
                if stage == "stall":
                    time.sleep(0.7)
                else:
                    for _ in range(50):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.02)
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    start = time.monotonic()
    token = chat_tools.provider_deadline.set(start + 0.2)
    response = None
    try:
        def read_response():
            nonlocal response
            response = provider_http.open_provider_request(
                urllib.request.Request(f"http://127.0.0.1:{server.server_port}/"), timeout=5,
            )
            with response:
                return provider_http.read_provider_body(response)
        if stage == "success":
            assert read_response() == b"ok"
            assert response.connection.watchdog.finished.is_set()
        else:
            with pytest.raises((ValueError, OSError, provider_http.http.client.HTTPException)):
                read_response()
        assert time.monotonic() - start < 1.5
        if response is not None:
            assert response.closed
    finally:
        chat_tools.provider_deadline.reset(token)
        server.shutdown()
        server.server_close()
        thread.join()


def test_ollama_assistant_uses_fixed_limits_and_structured_nonstreaming_transport(monkeypatch):
    from app.schemas.chat import ChatRequest

    requests = []
    monkeypatch.setattr(chat_tools, "_resolve_model", lambda *args: "synthetic")
    monkeypatch.setattr(chat_tools, "_resolve_endpoint", lambda *args: "http://127.0.0.1:11434/api/chat")
    monkeypatch.setattr(chat_tools, "_resolve_gpu_enabled", lambda *args: False)
    monkeypatch.setattr(chat_tools, "open_provider_request", lambda request, **kwargs: requests.append(request) or io.BytesIO())
    schema = {"type": "object"}
    messages = [{"role": "system", "content": "Bounded instructions"}, {"role": "user", "content": "Synthetic question"}]
    model, response = chat_tools._open_ollama_request(ChatRequest(message="Synthetic question"), messages=messages, output_schema=schema)
    response.close()
    body = json.loads(requests[0].data)
    assert model == "synthetic"
    assert body["stream"] is False
    assert body["messages"] == messages
    assert body["format"] == schema
    assert {key: body["options"][key] for key in ("temperature", "num_predict", "num_ctx")} == {
        "temperature": 0, "num_predict": 1024, "num_ctx": 8192,
    }
    with pytest.raises(ValueError, match="no valid messages"):
        chat_tools._open_ollama_request(ChatRequest(message="test"), messages=[])
    assert len(requests) == 1


def test_expired_operation_never_opens_next_request(monkeypatch):
    token = chat_tools.provider_deadline.set(1)
    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", lambda *a, **k: pytest.fail("Expired provider request opened"))
    try:
        with pytest.raises(ValueError, match="time limit"):
            provider_http.open_provider_request(urllib.request.Request("http://localhost/"), timeout=5)
    finally:
        chat_tools.provider_deadline.reset(token)


def test_deadline_https_handler_keeps_certificate_verification(monkeypatch):
    import ssl
    import time

    handler = provider_http._DeadlineHandlers()
    request = urllib.request.Request("https://provider.invalid/")
    request._copylot_deadline = time.monotonic() + 10

    def open_connection(factory, request, **kwargs):
        connection = factory("provider.invalid", timeout=1, **kwargs)
        assert isinstance(connection, provider_http._DeadlineHTTPSConnection)
        assert connection._context.verify_mode == ssl.CERT_REQUIRED
        assert connection._context.check_hostname
        if handler._context is not None:
            assert connection._context is handler._context
        return io.BytesIO(b"ok")

    monkeypatch.setattr(handler, "do_open", open_connection)
    response = handler.https_open(request)
    assert response.read() == b"ok"
    response.response.close()


@pytest.mark.parametrize("oversized", [False, True])
def test_provider_json_reads_are_bounded_and_closed(monkeypatch, oversized):
    monkeypatch.setenv("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", "64")

    class Body(io.BytesIO):
        def read(self, size=-1):
            assert size == 65
            return super().read(size)

    body = Body(json.dumps({"text": "x" * (100 if oversized else 10)}).encode())
    if oversized:
        with pytest.raises(ValueError, match="size limit"):
            provider_http.read_json_response(body, "Invalid JSON")
    else:
        assert provider_http.read_json_response(body, "Invalid JSON") == {"text": "x" * 10}
    assert body.closed


@pytest.mark.parametrize("body", [b'{"message":{"content":"reply"},"done_reason":"length"}', b'invalid-json', b'{"message":{"content":""}}'])
def test_assistant_rejects_incomplete_or_invalid_responses_and_closes_body(monkeypatch, body):
    from app.schemas.chat import ChatRequest
    response = io.BytesIO(body)
    monkeypatch.setattr(chat_tools, "_open_ollama_request", lambda *a, **k: ("synthetic", response))
    with pytest.raises(ValueError):
        chat_tools.assistant_completion(ChatRequest(message="test"), "instruction", "{}")
    assert response.closed


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize("scheme", ["http", "https"])
def test_redirects_never_send_a_second_request(monkeypatch, status, method, scheme):
    requests = []

    class Transport(urllib.request.BaseHandler):
        handler_order = 100

        def http_open(self, request):
            requests.append(request)
            headers = Message()
            headers["Location"] = "http://unapproved.invalid/private"
            response = urllib.response.addinfourl(io.BytesIO(b""), headers, request.full_url, status)
            response.msg = "Redirect"
            return response

        https_open = http_open

    opener = urllib.request.build_opener(provider_http._NoProviderRedirects(), Transport())
    monkeypatch.setattr(provider_http, "PROVIDER_OPENER", opener)
    request = urllib.request.Request(
        f"{scheme}://127.0.0.1:11434/api/chat", method=method,
        headers={"Authorization": "Bearer synthetic-secret"},
        data=b"private context" if method != "GET" else None,
    )
    with pytest.raises(ValueError):
        provider_http.open_provider_request(request, timeout=1)
    assert requests == [request]


def test_http_error_body_is_not_read_and_is_closed(monkeypatch):
    class UnreadableBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("Upstream error bodies must not be read")

    body = UnreadableBody(b"synthetic-secret")

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://provider.invalid", 401, "synthetic-secret", {}, body)

    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", fail)
    with pytest.raises(ValueError, match=r"request failed \(HTTP 401\)") as error:
        provider_http.open_provider_request(urllib.request.Request("https://provider.invalid"), timeout=1)
    assert "synthetic-secret" not in str(error.value)
    assert error.value.__suppress_context__
    assert body.closed


@pytest.mark.parametrize("provider,payload", [
    ("openai", {"choices": [{"message": {"content": "Synthetic reply"}}]}),
    ("anthropic", {"content": [{"type": "text", "text": "Synthetic reply"}]}),
    ("gemini", {"candidates": [{"content": {"parts": [{"text": "Synthetic reply"}]}}]}),
])
def test_cloud_success_still_uses_authenticated_post(monkeypatch, provider, payload):
    response = io.BytesIO(json.dumps(payload).encode())
    requests = []

    def open_request(request, **kwargs):
        requests.append(request)
        assert request.get_method() == "POST"
        assert "synthetic-secret" in str(request.headers)
        return response

    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", open_request)
    result = getattr(chat_tools, f"_{provider}_chat_text")(
        model="synthetic-model", api_key="synthetic-secret",
        messages=[{"role": "user", "content": "Hello"}], temperature=0.2, max_tokens=20,
    )
    assert result == "Synthetic reply"
    assert len(requests) == 1 and response.closed
    if provider == 'anthropic':
        body = json.loads(requests[0].data)
        assert not {'temperature', 'top_p', 'top_k'} & body.keys()


def test_connection_error_reason_is_not_exposed(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("synthetic-secret")

    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", fail)
    with pytest.raises(ValueError, match="Could not reach") as error:
        provider_http.open_provider_request(urllib.request.Request("https://provider.invalid"), timeout=1)
    assert "synthetic-secret" not in str(error.value)

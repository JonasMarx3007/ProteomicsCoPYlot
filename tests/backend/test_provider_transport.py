import io
import json
import urllib.error
import urllib.request
import urllib.response
from email.message import Message

import pytest

from app.services import chat_tools


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
            response = chat_tools._open_provider_request(
                urllib.request.Request(f"http://127.0.0.1:{server.server_port}/"), timeout=5,
            )
            with response:
                return chat_tools._read_provider_body(response)
        if stage == "success":
            assert read_response() == b"ok"
            assert response.connection.watchdog.finished.is_set()
        else:
            with pytest.raises((ValueError, OSError, chat_tools.http.client.HTTPException)):
                read_response()
        assert time.monotonic() - start < 1.5
        if response is not None:
            assert response.closed
    finally:
        chat_tools.provider_deadline.reset(token)
        server.shutdown()
        server.server_close()
        thread.join()


def test_expired_operation_never_opens_next_request(monkeypatch):
    token = chat_tools.provider_deadline.set(1)
    monkeypatch.setattr(chat_tools._PROVIDER_OPENER, "open", lambda *a, **k: pytest.fail("Expired continuation opened"))
    try:
        with pytest.raises(ValueError, match="time limit"):
            chat_tools._open_provider_request(urllib.request.Request("http://localhost/"), timeout=5)
    finally:
        chat_tools.provider_deadline.reset(token)


def test_deadline_https_handler_keeps_certificate_verification(monkeypatch):
    import ssl
    import time

    handler = chat_tools._DeadlineHandlers()
    request = urllib.request.Request("https://provider.invalid/")
    request._copylot_deadline = time.monotonic() + 10

    def open_connection(factory, request, **kwargs):
        connection = factory("provider.invalid", timeout=1, **kwargs)
        assert isinstance(connection, chat_tools._DeadlineHTTPSConnection)
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
            chat_tools._read_json_response(body, "Invalid JSON")
    else:
        assert chat_tools._read_json_response(body, "Invalid JSON") == {"text": "x" * 10}
    assert body.closed


def _stream_fixture(monkeypatch, bodies):
    from app.schemas.chat import OllamaChatRequest

    pending = iter(bodies)
    monkeypatch.setattr(chat_tools, "_open_ollama_request", lambda *a, **k: ("synthetic", next(pending), []))
    return chat_tools.ollama_chat_stream(OllamaChatRequest(message="test"))[1]


@pytest.mark.parametrize("violation", ["line", "total", "continuation"])
def test_stream_limits_include_malformed_lines_and_continuations(monkeypatch, violation):
    line = json.dumps({"message": {"content": "reply"}, "done": True, "done_reason": "length"}).encode() + b"\n"
    if violation == "line":
        monkeypatch.setenv("COPYLOT_PROVIDER_LINE_MAX_BYTES", "16")
        bodies = [io.BytesIO(b"x" * 100)]
    elif violation == "total":
        monkeypatch.setenv("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", "64")
        bodies = [io.BytesIO(b"invalid\n" * 20)]
    else:
        monkeypatch.setenv("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", str(len(line) + 5))
        bodies = [io.BytesIO(line), io.BytesIO(line)]
    stream = _stream_fixture(monkeypatch, bodies)
    with pytest.raises(ValueError, match="size limit"):
        list(stream)
    assert all(body.closed for body in bodies)


@pytest.mark.parametrize("failure_at", ["start", "body", "none"])
@pytest.mark.parametrize("route_name", ["chat_stream_route", "ollama_chat_stream_route"])
def test_stream_response_closes_upstream_on_send_failure(monkeypatch, failure_at, route_name):
    import asyncio
    from starlette.requests import ClientDisconnect
    from app.api import routes_chat
    from app.schemas.chat import OllamaChatRequest

    body = io.BytesIO(b'{"message":{"content":"hello"},"done":true}\n')
    stream = _stream_fixture(monkeypatch, [body])
    monkeypatch.setattr(routes_chat, "ai_mode_enabled", lambda: True)
    monkeypatch.setattr(routes_chat, "chat_stream", lambda _: ("ollama", "synthetic", stream))
    monkeypatch.setattr(routes_chat, "ollama_chat_stream", lambda _: ("synthetic", stream))
    response = getattr(routes_chat, route_name)(OllamaChatRequest(message="test"))

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response." + failure_at:
                raise OSError("synthetic disconnect")

        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    if failure_at == "none":
        asyncio.run(run())
    else:
        with pytest.raises(ClientDisconnect):
            asyncio.run(run())
    assert body.closed


def test_unstarted_stream_can_be_closed(monkeypatch):
    body = io.BytesIO(b"")
    stream = _stream_fixture(monkeypatch, [body])
    stream.close()
    stream.close()
    assert body.closed


def test_legacy_asgi_disconnect_closes_unstarted_upstream(monkeypatch):
    import asyncio
    from app.api.routes_chat import _ClosingStreamingResponse

    body = io.BytesIO(b'{"message":{"content":"hello"}}\n')
    stream = _stream_fixture(monkeypatch, [body])

    async def run():
        async def receive():
            return {"type": "http.disconnect"}

        async def send(_message):
            await asyncio.sleep(0)

        await _ClosingStreamingResponse(stream)(
            {"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send
        )

    asyncio.run(run())
    assert body.closed


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

    opener = urllib.request.build_opener(chat_tools._NoProviderRedirects(), Transport())
    monkeypatch.setattr(chat_tools, "_PROVIDER_OPENER", opener)
    request = urllib.request.Request(
        f"{scheme}://127.0.0.1:11434/api/chat", method=method,
        headers={"Authorization": "Bearer synthetic-secret"},
        data=b"private context" if method != "GET" else None,
    )
    with pytest.raises(ValueError):
        chat_tools._open_provider_request(request, timeout=1)
    assert requests == [request]


def test_http_error_body_is_not_read_and_is_closed(monkeypatch):
    class UnreadableBody(io.BytesIO):
        def read(self, *args):
            pytest.fail("Upstream error bodies must not be read")

    body = UnreadableBody(b"synthetic-secret")

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://provider.invalid", 401, "synthetic-secret", {}, body)

    monkeypatch.setattr(chat_tools._PROVIDER_OPENER, "open", fail)
    with pytest.raises(ValueError, match=r"request failed \(HTTP 401\)") as error:
        chat_tools._open_provider_request(urllib.request.Request("https://provider.invalid"), timeout=1)
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

    monkeypatch.setattr(chat_tools._PROVIDER_OPENER, "open", open_request)
    result = getattr(chat_tools, f"_{provider}_chat_text")(
        model="synthetic-model", api_key="synthetic-secret",
        messages=[{"role": "user", "content": "Hello"}], temperature=0.2, max_tokens=20,
    )
    assert result == "Synthetic reply"
    assert len(requests) == 1 and response.closed


def test_connection_error_reason_is_not_exposed(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("synthetic-secret")

    monkeypatch.setattr(chat_tools._PROVIDER_OPENER, "open", fail)
    with pytest.raises(ValueError, match="Could not reach") as error:
        chat_tools._open_provider_request(urllib.request.Request("https://provider.invalid"), timeout=1)
    assert "synthetic-secret" not in str(error.value)

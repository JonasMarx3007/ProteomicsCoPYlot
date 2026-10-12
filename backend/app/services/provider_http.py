"""HTTP to an AI provider: the opener, its deadline, and how a reply is read.

Shared by the cloud/Ollama path (`chat_tools`) and the local GLM server path
(`local_ai_server`); neither imports the other for it. Redirects are refused
(a provider endpoint is configured, not discovered), every connection carries
the request's deadline, and a body is read up to a configured limit.
"""
from __future__ import annotations

import http.client
import json
import socket
from threading import Timer
import time
import urllib.error
import urllib.request

from app.services.env_settings import env_int
from app.services.workload_manager import provider_deadline


class _NoProviderRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _DeadlineConnection:
    def connect(self):
        super().connect()
        sock = self.sock

        def expire():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        self.watchdog = Timer(max(0, self.deadline - time.monotonic()), expire)
        self.watchdog.daemon = True
        self.watchdog.start()


class _DeadlineHTTPConnection(_DeadlineConnection, http.client.HTTPConnection):
    pass


class _DeadlineHTTPSConnection(_DeadlineConnection, http.client.HTTPSConnection):
    pass


class _TimedResponse:
    def __init__(self, response, connection):
        self.response = response
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.response, name)

    def read(self, size=-1):
        if time.monotonic() >= self.connection.deadline:
            raise ValueError("Provider operation exceeded its time limit.")
        result = self.response.read(size)
        if time.monotonic() >= self.connection.deadline:
            raise ValueError("Provider operation exceeded its time limit.")
        return result

    def readline(self, size=-1):
        if time.monotonic() >= self.connection.deadline:
            raise ValueError("Provider operation exceeded its time limit.")
        return self.response.readline(size)

    def __iter__(self):
        # A streamed reply (server-sent events) is read line by line, each under the deadline.
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def close(self):
        self.connection.watchdog.cancel()
        self.response.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _DeadlineHandlers(urllib.request.HTTPHandler, urllib.request.HTTPSHandler):
    def _open(self, request, connection_class, **kwargs):
        connections = []

        def connection(*args, **options):
            conn = connection_class(*args, **options)
            conn.deadline = request._copylot_deadline
            connections.append(conn)
            return conn

        try:
            response = self.do_open(connection, request, **kwargs)
            return _TimedResponse(response, connections[0])
        except BaseException:
            for conn in connections:
                if hasattr(conn, "watchdog"):
                    conn.watchdog.cancel()
            raise

    def http_open(self, request):
        return self._open(request, _DeadlineHTTPConnection)

    def https_open(self, request):
        return self._open(request, _DeadlineHTTPSConnection, context=self._context)


PROVIDER_OPENER = urllib.request.build_opener(_NoProviderRedirects(), _DeadlineHandlers())


def read_provider_body(response) -> bytes:
    limit = max(1, env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024))
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Provider response exceeds the configured size limit.")
    return body


def open_provider_request(request, *, timeout, provider="Ollama"):
    now = time.monotonic()
    deadline = min(provider_deadline.get() or now + timeout, now + timeout)
    if deadline <= now:
        raise ValueError("Provider operation exceeded its time limit.")
    request._copylot_deadline = deadline
    try:
        return PROVIDER_OPENER.open(request, timeout=deadline - now)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if 300 <= status < 400:
            raise ValueError(f"{provider} redirect blocked. Configure the final endpoint directly.") from None
        raise ValueError(f"{provider} request failed (HTTP {status}).") from None
    except urllib.error.URLError:
        raise ValueError(f"Could not reach {provider}. Check the endpoint and connection.") from None


def openai_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = str(part.get("text", "")).strip()
                if text:
                    chunks.append(text)
            elif isinstance(part, str):
                text = part.strip()
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return ""


def read_json_response(response, invalid_json_message: str) -> dict[str, object]:
    with response:
        payload = read_provider_body(response).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(payload)
    except Exception as exc:
        raise ValueError(invalid_json_message) from exc
    if not isinstance(parsed, dict):
        raise ValueError(invalid_json_message)
    return parsed


class AssistantContextExhausted(ValueError):
    """The request and reply do not fit the model's context window."""

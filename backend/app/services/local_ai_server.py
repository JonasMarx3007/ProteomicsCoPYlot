"""Local AI servers that speak the OpenAI-compatible API (llama.cpp, vLLM, LM Studio, ...).

Such a server answers `GET <base>/models` and `POST <base>/chat/completions`
(the base usually ends in `/v1`), but not Ollama's `/api/tags` and `/api/chat`.
It is treated like Ollama, not like a cloud provider: the analysis context is
sent in full and no cloud consent is asked for, because the data stays on a
machine the operator chose. On a desktop run the person at the keyboard is the
operator, so any address they enter is used. A deployment (tool passwords, a
viewer or a viewer portal) only reaches addresses its operator listed
(`COPYLOT_LOCAL_AI_URL`, `COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS`): there the
server would otherwise send analysis data wherever a visitor points it.

What Ollama offers and these servers do not is left out rather than imitated:
the context size is fixed when the server starts (it is read from llama.cpp's
`/props` where available), and there is no GPU switch or model management.
What the server does report about its model -- llama.cpp's parameter count,
trained context and image support -- is read so the assistant level reflects
the real model (`model_metadata`).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.schemas.chat import ChatRequest, OllamaModelsResponse
from app.services.env_settings import env_flag, env_int

PROVIDER = "openai_compatible"
LABEL = "Local server (OpenAI-compatible)"
_DEFAULT_CONTEXT_TOKENS = 8192
_SCHEMA_REJECTED_HINTS = ("response_format", "json_schema", "grammar", "schema")
_CONTEXT_EXCEEDED_HINTS = ("context", "n_ctx", "too long", "maximum context", "exceed")
_EMBEDDING_MARKERS = ("embedding", "embed-", "embed:", "nomic-embed", "all-minilm", "bge-")
_METADATA_TTL_SECONDS = 300
_METADATA_CACHE: dict[str, tuple[float, dict]] = {}
_METADATA_LOCK = threading.Lock()
# Models seen returning separate reasoning text: their thinking needs reply room.
_REASONING_SEEN: set[str] = set()


def _desktop_run() -> bool:
    return not any(env_flag(name) for name in (
        "COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED"))


def _origin(url: str) -> tuple[str, str, int | None] | None:
    text = url.strip()
    if not text:
        return None
    if not text.lower().startswith(("http://", "https://")):
        text = f"http://{text}"
    parts = urllib.parse.urlsplit(text)
    if not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parts.scheme.lower() == "https" else 80
    return parts.scheme.lower(), parts.hostname.lower().rstrip("."), port


def default_server_url() -> str:
    return str(os.getenv("COPYLOT_LOCAL_AI_URL", "")).strip()


def _allowed_origins() -> set[tuple[str, str, int | None]]:
    values = [default_server_url(), *str(os.getenv("COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS", "")).split(",")]
    return {origin for origin in map(_origin, values) if origin is not None}


def resolve_base_url(value: str | None) -> str:
    """The server's API base (`.../v1`), after checking the operator allows it.

    Accepts the base itself (`http://host:8084/v1`), the bare server
    (`http://host:8084`, `/v1` is added) or a full endpoint URL
    (`.../v1/chat/completions`, `.../v1/models`, which are cut back).
    """
    text = str(value or "").strip() or default_server_url()
    if not text:
        raise ValueError("Enter the address of the local AI server, for example http://127.0.0.1:8080/v1.")
    if "://" in text and not text.lower().startswith(("http://", "https://")):
        raise ValueError("The local AI server address must be an http or https URL.")
    if not text.lower().startswith(("http://", "https://")):
        text = f"http://{text}"
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("The local AI server address must be an http or https URL.")
    if parts.username or parts.password:
        raise ValueError("The local AI server address must not contain credentials; use the API key field.")
    if parts.query or parts.fragment:
        raise ValueError("The local AI server address must not contain a query string or fragment.")
    origin = _origin(text)
    if origin is None:
        raise ValueError("The local AI server address has an invalid port.")
    # A stored server credential must never follow an arbitrary browser URL,
    # including on a desktop run. Bind it to operator-configured origins.
    stored_key = str(os.getenv("COPYLOT_LOCAL_AI_API_KEY", "")).strip()
    if origin not in _allowed_origins() and (not _desktop_run() or stored_key):
        raise ValueError(
            "This deployment only reaches local AI servers its operator allowed. Ask the "
            "administrator to add " + parts.scheme.lower() + "://" + parts.netloc + " to COPYLOT_LOCAL_AI_ALLOWED_ENDPOINTS "
            "(or to set it as COPYLOT_LOCAL_AI_URL)."
        )
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/models"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
            break
    if not path:
        path = "/v1"
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def _api_key(payload_key: str | None) -> str:
    """The server's key wins over one typed in the browser (see chat_tools._resolve_api_key)."""
    return str(os.getenv("COPYLOT_LOCAL_AI_API_KEY", "")).strip() or str(payload_key or "").strip()


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _get_json(url: str, api_key: str, *, timeout: float) -> dict:
    from app.services.chat_tools import _open_provider_request, _read_json_response

    request = urllib.request.Request(url, headers=_headers(api_key), method="GET")
    response = _open_provider_request(request, timeout=timeout, provider="The local AI server")
    return _read_json_response(response, "The local AI server returned invalid JSON.")


def server_models(endpoint: str | None, api_key: str | None = None) -> OllamaModelsResponse:
    """The models the server offers (`GET <base>/models`)."""
    warnings: list[str] = []
    models: list[str] = []
    try:
        base = resolve_base_url(endpoint)
        parsed = _get_json(f"{base}/models", _api_key(api_key), timeout=12)
        data, legacy = parsed.get("data"), parsed.get("models")
        entries: list = data if isinstance(data, list) else legacy if isinstance(legacy, list) else []
        for entry in entries:
            name = str((entry.get("id") or entry.get("name") or entry.get("model")) if isinstance(entry, dict) else entry or "").strip()
            if name and not any(marker in name.lower() for marker in _EMBEDDING_MARKERS):
                models.append(name)
        models = list(dict.fromkeys(models))
    except ValueError as exc:
        warnings.append(str(exc))
    preferred = str(os.getenv("COPYLOT_LOCAL_AI_MODEL", "")).strip()
    selected = preferred if preferred and (not models or preferred in models) else (models[0] if models else None)
    if not models and not warnings:
        warnings.append("The local AI server reported no models.")
    return OllamaModelsResponse(models=models, selectedModel=selected, warnings=warnings)


def context_tokens(endpoint: str | None, api_key: str | None = None) -> int:
    """The server's context window.

    llama.cpp reports it at `/props`; other servers do not expose it, so
    `COPYLOT_LOCAL_AI_CONTEXT_TOKENS` (default 8192) is used instead. The
    environment value always wins: it is how an operator states the truth when
    the server cannot.
    """
    configured = env_int("COPYLOT_LOCAL_AI_CONTEXT_TOKENS", 0, minimum=0)
    if configured:
        return max(2048, configured)
    try:
        base = resolve_base_url(endpoint)
        root = base[: -len("/v1")] if base.endswith("/v1") else base
        props = _get_json(f"{root}/props", _api_key(api_key), timeout=6)
        settings = props.get("default_generation_settings")
        value = (settings.get("n_ctx") if isinstance(settings, dict) else None) or props.get("n_ctx")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return max(2048, value)
    except ValueError:
        pass
    return _DEFAULT_CONTEXT_TOKENS


def model_metadata(endpoint: str | None, model: str, api_key: str | None = None) -> dict:
    """What the server says about one model: {params_b, context, vision, reasoning}.

    llama.cpp lists `meta.n_params` and `meta.n_ctx_train` under `/v1/models`,
    a `multimodal` capability in its Ollama-style `models` list, and
    `modalities.vision` at `/props`. Other servers report less; missing values
    stay None. Cached for five minutes per server and model.
    """
    try:
        base = resolve_base_url(endpoint)
    except ValueError:
        return {}
    key = f"{base}|{model}"
    now = time.monotonic()
    with _METADATA_LOCK:
        cached = _METADATA_CACHE.get(key)
        if cached and now - cached[0] < _METADATA_TTL_SECONDS:
            return dict(cached[1])
    found: dict = {"params_b": None, "context": None, "vision": None, "effort": False, "tools": False,
                   "reasoning": True if model in _REASONING_SEEN else None}
    secret = _api_key(api_key)
    try:
        listed = _get_json(f"{base}/models", secret, timeout=8)
        for entry in listed.get("data") or []:
            if isinstance(entry, dict) and model in {entry.get("id"), *(entry.get("aliases") or [])}:
                meta: dict = entry["meta"] if isinstance(entry.get("meta"), dict) else {}
                params = meta.get("n_params")
                if isinstance(params, (int, float)) and not isinstance(params, bool) and params > 0:
                    found["params_b"] = round(float(params) / 1e9, 2)
                trained = meta.get("n_ctx_train")
                if isinstance(trained, int) and not isinstance(trained, bool) and trained > 0:
                    found["trained_context"] = trained
        for entry in listed.get("models") or []:
            if isinstance(entry, dict) and model in {entry.get("name"), entry.get("model")}:
                capabilities = {str(item).lower() for item in entry.get("capabilities") or []}
                if capabilities:
                    found["vision"] = bool(capabilities & {"multimodal", "vision"})
    except ValueError:
        pass
    try:
        root = base[: -len("/v1")] if base.endswith("/v1") else base
        props = _get_json(f"{root}/props", secret, timeout=6)
        modalities = props.get("modalities")
        if isinstance(modalities, dict) and isinstance(modalities.get("vision"), bool):
            found["vision"] = modalities["vision"]
        caps = props.get("chat_template_caps")
        if isinstance(caps, dict) and caps.get("supports_reasoning_effort") is True:
            found["reasoning"] = True
            found["effort"] = True
        if isinstance(caps, dict) and (caps.get("supports_tool_calls") or caps.get("supports_tools")
                                       or caps.get("supports_parallel_tool_calls")):
            found["tools"] = True
    except ValueError:
        pass
    found["context"] = context_tokens(endpoint, api_key)
    with _METADATA_LOCK:
        _METADATA_CACHE[key] = (now, dict(found))
    return found


def request_timeout() -> float:
    """Seconds one local-server reply may take (`COPYLOT_LOCAL_AI_TIMEOUT`, default 300).

    Large local models answer at tens of tokens per second; a model that thinks
    for 2,000 tokens needs over a minute before its plan begins."""
    return float(env_int("COPYLOT_LOCAL_AI_TIMEOUT", 300, minimum=30))


def _post(url: str, body: dict, api_key: str, progress_id: str | None = None) -> tuple[int, dict | None, str]:
    """(status, parsed JSON or None, error text). HTTP errors are returned, not raised,
    because their text says whether the schema or the context was the problem.

    With a ``progress_id`` the reply is streamed and the phase and token count
    are published for the chat's progress line (assistant_progress); the
    result is assembled into the same shape as an ordinary reply."""
    from app.services.chat_tools import _read_json_response, _read_provider_body

    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=_headers(api_key), method="POST")
    try:
        response = _open_provider_request_raising(request)
    except urllib.error.HTTPError as exc:
        try:
            text = _read_provider_body(exc).decode("utf-8", errors="replace")[:2000]
        except Exception:
            text = ""
        finally:
            exc.close()
        return exc.code, None, text
    if not body.get("stream"):
        return 200, _read_json_response(response, "The local AI server returned invalid JSON."), ""
    return 200, _read_stream(response, progress_id), ""


def _read_stream(response, progress_id: str | None) -> dict:
    """Assemble a streamed chat completion, publishing progress as it arrives."""
    from app.services import assistant_progress
    from app.services.chat_tools import provider_deadline

    content: list[str] = []
    reasoning = 0
    produced = 0
    finish = None
    usage = None
    calls: dict[int, dict] = {}
    deadline = provider_deadline.get()
    limit = env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024)
    received = 0
    with response:
        for raw in response:
            received += len(raw)
            if received > limit:
                raise ValueError("Provider response exceeds the configured size limit.")
            if deadline is not None and time.monotonic() >= deadline:
                raise ValueError("Provider operation exceeded its time limit.")
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning += 1
                if delta.get("content"):
                    content.append(str(delta["content"]))
                for call in delta.get("tool_calls") or []:
                    slot = calls.setdefault(int(call.get("index", 0)), {"id": "", "type": "function",
                                                                        "function": {"name": "", "arguments": ""}})
                    slot["id"] = call.get("id") or slot["id"]
                    function = call.get("function") or {}
                    slot["function"]["name"] += function.get("name") or ""
                    slot["function"]["arguments"] += function.get("arguments") or ""
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
            produced += 1
            assistant_progress.update(progress_id, "answering" if content or calls else "thinking", produced)
    message: dict = {"role": "assistant", "content": "".join(content),
                     "reasoning_content": "x" if reasoning else ""}
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
    return {"choices": [{"index": 0, "finish_reason": finish, "message": message}], "usage": usage}


def _open_provider_request_raising(request):
    """`chat_tools._open_provider_request`, except that a 4xx/5xx reaches the caller."""
    from app.services import chat_tools

    now = time.monotonic()
    limit = request_timeout()
    deadline = min(chat_tools.provider_deadline.get() or now + limit, now + limit)
    if deadline <= now:
        raise ValueError("Provider operation exceeded its time limit.")
    request._copylot_deadline = deadline
    try:
        return chat_tools._PROVIDER_OPENER.open(request, timeout=deadline - now)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            exc.close()
            raise ValueError("The local AI server redirected the request. Configure the final address directly.") from None
        raise
    except urllib.error.URLError:
        raise ValueError("Could not reach the local AI server. Check the address and connection.") from None


def chat_message(payload: ChatRequest, messages: list[dict], *, model: str, schema: dict | None,
                 context_window: int, max_tokens: int = 1024, image: str | None = None,
                 tools: list[dict] | None = None, effort: str | None = None) -> dict:
    """One completion; returns the assistant message (content and any tool calls).

    Raises AssistantContextExhausted when the window is too small. ``image`` is
    a data URL of the rendered plot, sent with the last user message to a model
    that reads images. ``effort`` is a reasoning effort for servers whose chat
    template supports it; ``COPYLOT_LOCAL_AI_REASONING_EFFORT`` overrides it
    (``server`` leaves the server's own default)."""
    from app.services.chat_tools import AssistantContextExhausted

    base = resolve_base_url(payload.localServerUrl)
    sent: list[dict] = [dict(message) for message in messages]
    if image:
        last_user = max((index for index, message in enumerate(sent) if message.get("role") == "user"), default=None)
        if last_user is not None and isinstance(sent[last_user].get("content"), str):
            sent[last_user]["content"] = [{"type": "text", "text": str(sent[last_user]["content"])},
                                          {"type": "image_url", "image_url": {"url": image}}]
    progress_id = getattr(payload, "progressId", None)
    body: dict[str, object] = {
        "model": model,
        "messages": sent,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": bool(progress_id),
    }
    if progress_id:
        body["stream_options"] = {"include_usage": True}
    configured = str(os.getenv("COPYLOT_LOCAL_AI_REASONING_EFFORT", "")).strip().lower()
    chosen = configured if configured in {"low", "medium", "high", "server"} else (effort or "")
    if chosen in {"low", "medium", "high"} and (configured or model_metadata(payload.localServerUrl, model, payload.apiKey).get("effort")):
        body["reasoning_effort"] = chosen
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "required"
    elif schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "copylot_answer", "schema": schema, "strict": True}}
    key = _api_key(payload.apiKey)
    status, parsed, error = _post(f"{base}/chat/completions", body, key, progress_id)
    lowered = error.lower()
    if status == 400 and "response_format" in body and any(hint in lowered for hint in _SCHEMA_REJECTED_HINTS) \
            and not any(hint in lowered for hint in _CONTEXT_EXCEEDED_HINTS):
        # Not every server supports structured output; the answer is still
        # validated against the schema by the caller.
        body.pop("response_format")
        status, parsed, error = _post(f"{base}/chat/completions", body, key, progress_id)
        lowered = error.lower()
    if status != 200 or parsed is None:
        if status in (400, 413) and any(hint in lowered for hint in _CONTEXT_EXCEEDED_HINTS):
            raise AssistantContextExhausted(
                f"The request does not fit the local AI server's {context_window}-token context window. "
                "Nothing was changed. Ask a narrower question, or start the server with a larger context.")
        if status in (401, 403):
            raise ValueError("The local AI server refused the request; check its API key.")
        if status == 404:
            raise ValueError(f"The local AI server does not know the model '{model}' or the address is wrong.")
        if tools and status == 400 and "tool" in lowered:
            raise ToolsUnsupported(error[:300])
        raise ValueError(f"The local AI server request failed (HTTP {status}).")
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("The local AI server's answer contained no choices.")
    first = choices[0]
    usage = parsed.get("usage")
    total = usage.get("total_tokens") if isinstance(usage, dict) else None
    if isinstance(total, int) and not isinstance(total, bool) and total >= context_window:
        raise AssistantContextExhausted(
            f"The request filled the local AI server's {context_window}-token context window before the reply "
            "was complete. Nothing was changed. Ask a narrower question.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("The local AI server's answer contained no message.")
    if str(message.get("reasoning_content") or "").strip():
        _REASONING_SEEN.add(model)
    if first.get("finish_reason") == "length":
        used = usage.get("completion_tokens") if isinstance(usage, dict) else None
        thinking = " most of it on thinking" if message.get("reasoning_content") else ""
        raise ValueError(
            f"The model used its whole reply budget ({used or max_tokens} tokens){thinking} before it finished. "
            "Nothing was changed. Ask for a smaller step, or raise the assistant level if this model can handle more.")
    return message


class ToolsUnsupported(ValueError):
    """The server refused tool calling; the caller falls back to the JSON plan."""


def chat_text(payload: ChatRequest, messages: list[dict[str, str]], *, model: str,
              schema: dict | None, context_window: int, max_tokens: int = 1024,
              image: str | None = None, effort: str | None = None) -> str:
    """One completion's text (reasoning models' thinking is left out)."""
    from app.services.chat_tools import _openai_content_to_text

    message = chat_message(payload, messages, model=model, schema=schema, context_window=context_window,
                           max_tokens=max_tokens, image=image, effort=effort)
    text = _openai_content_to_text(message.get("content"))
    if not text.strip():
        raise ValueError("The local AI server returned an empty answer.")
    return text

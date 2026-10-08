from __future__ import annotations

import json
import math
import ipaddress
import http.client
import os
import re
import shutil
import subprocess
import socket
import time
from threading import Lock, Timer
import urllib.error
import urllib.parse
import urllib.request

from app.schemas.chat import (
    ChatProvider,
    ChatRequest,
    OllamaGpuStatusResponse,
    ModelCapabilityResponse,
    OllamaModelManageResponse,
    OllamaModelsResponse,
)
from app.services.assistant_profiles import LEVEL_NAMES, LEVELS, classify_model, input_limit, output_tokens, reasoning_model
from app.services.cloud_ai_consent import require_cloud_ai_consent
from app.services.workload_manager import provider_deadline
from app.services.env_settings import env_flag, env_float, env_int


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


_PROVIDER_OPENER = urllib.request.build_opener(_NoProviderRedirects(), _DeadlineHandlers())


def _read_provider_body(response) -> bytes:
    limit = max(1, env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024))
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Provider response exceeds the configured size limit.")
    return body


def _open_provider_request(request, *, timeout, provider="Ollama"):
    now = time.monotonic()
    deadline = min(provider_deadline.get() or now + timeout, now + timeout)
    if deadline <= now:
        raise ValueError("Provider operation exceeded its time limit.")
    request._copylot_deadline = deadline
    try:
        return _PROVIDER_OPENER.open(request, timeout=deadline - now)
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
        if 300 <= status < 400:
            raise ValueError(f"{provider} redirect blocked. Configure the final endpoint directly.") from None
        raise ValueError(f"{provider} request failed (HTTP {status}).") from None
    except urllib.error.URLError:
        raise ValueError(f"Could not reach {provider}. Check the endpoint and connection.") from None


_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
_OLLAMA_DEFAULT_PORT = 11434
# Names Ollama itself accepts: registry/repo:tag, letters, digits, . _ - / :
_OLLAMA_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$")

_GPU_STATUS_CACHE_TTL_SECONDS = 60.0
_GPU_STATUS_CACHE: dict[str, tuple[float, OllamaGpuStatusResponse]] = {}
_MODELS_CACHE_TTL_SECONDS = 30.0
_MODELS_CACHE: dict[str, tuple[float, list[str]]] = {}
_MODEL_CAPABILITY_CACHE_TTL_SECONDS = 300.0
_MODEL_CAPABILITY_CACHE: dict[str, tuple[float, ModelCapabilityResponse]] = {}
_CACHE_LOCK = Lock()
_CACHE_GENERATION = 0
_CACHE_MAX_ENTRIES = 128


def _cache_get(cache, key, ttl):
    with _CACHE_LOCK:
        now = time.monotonic()
        for expired in [k for k, (created, _) in cache.items() if now - created > ttl]:
            del cache[expired]
        hit = cache.get(key)
        return (hit[1] if hit is not None else None), _CACHE_GENERATION


def _cache_put(cache, key, value, generation):
    with _CACHE_LOCK:
        if generation != _CACHE_GENERATION or len(key) > 1024:
            return
        cache.pop(key, None)
        while len(cache) >= _CACHE_MAX_ENTRIES:
            del cache[next(iter(cache))]
        cache[key] = (time.monotonic(), value)


_DEFAULT_MODEL_MANAGE_TIMEOUT_SECONDS = 1800
# The one list of cloud default models; the browser reads it from
# /api/chat/provider-defaults instead of keeping its own. Checked against the
# providers' model lists on 2026-10-02 (gemini-2.0-flash was shut down on
# 2026-06-01). An administrator can override each without a release:
# COPYLOT_DEFAULT_OPENAI_MODEL, COPYLOT_DEFAULT_ANTHROPIC_MODEL, COPYLOT_DEFAULT_GEMINI_MODEL.
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-5.4-mini",
    "anthropic": "claude-sonnet-5-5",
    "gemini": "gemini-3.8-flash",
}
_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_MESSAGES_ENDPOINT = "https://api.anthropic.com/v1/messages"
_GEMINI_BASE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
_CLOUD_MAX_CONTEXT_CHARS = 96_000
ASSISTANT_INPUT_MAX_CHARS = 24_000
_PROTECTED_CONTEXT_PATTERNS = (
    # Windows drive and UNC paths, and file URLs.
    re.compile(r"(?i)(?:^|[\s'\"(=,])(?:[a-z]:[\\/]|\\\\|file://)"),
    # Linux and macOS paths: a home directory or a common mount or system root,
    # starting a token. API paths ("/api/...") and plain words are not matched.
    re.compile(r"(?:^|[\s'\"(=,])(?:~/|/(?:home|Users|root|mnt|media|Volumes|tmp|var|opt|srv|private)/)"),
    re.compile(r"(?i)(?:api[-_ ]?key|authorization|access[-_ ]?token|password)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def ai_mode_enabled() -> bool:
    return env_flag("COPYLOT_AI_MODE")


def _resolve_provider(payload_provider: str | None) -> ChatProvider:
    value = str(payload_provider or "").strip().lower()
    if value in _ALL_PROVIDERS:
        return value
    return "ollama"


_ALL_PROVIDERS = ("ollama", "openai_compatible", "openai", "anthropic", "gemini")
# Providers on machines the operator controls: the analysis context goes in
# full and no cloud consent is asked for (see local_ai_server).
LOCAL_PROVIDERS = ("ollama", "openai_compatible")


def allowed_ai_providers() -> list[str]:
    """Providers the operator allows: COPYLOT_AI_ALLOWED_PROVIDERS (comma list), else all."""
    raw = str(os.getenv("COPYLOT_AI_ALLOWED_PROVIDERS", "")).strip().lower()
    if not raw:
        return list(_ALL_PROVIDERS)
    chosen = {item.strip() for item in raw.split(",") if item.strip()}
    return [provider for provider in _ALL_PROVIDERS if provider in chosen]


def allowed_ai_models() -> dict[str, list[str]]:
    """Models the operator allows per provider, from COPYLOT_AI_ALLOWED_MODELS.

    Entries are "provider:model", comma-separated. A provider without an entry
    is unrestricted, so an operator can pin the cloud models a server key may
    spend while leaving local models open.
    """
    allowed: dict[str, list[str]] = {}
    for item in str(os.getenv("COPYLOT_AI_ALLOWED_MODELS", "")).split(","):
        provider, _, model = item.strip().partition(":")
        provider = provider.strip().lower()
        if provider in _ALL_PROVIDERS and model.strip():
            allowed.setdefault(provider, []).append(model.strip())
    return allowed


def check_ai_operator_policy(provider: str, model: str) -> None:
    """Refuse a provider or model the operator has not allowed on this server."""
    if provider not in allowed_ai_providers():
        raise ValueError(f"This server does not allow the AI provider '{provider}'.")
    models = allowed_ai_models().get(provider)
    if models is not None and model not in models:
        raise ValueError(
            f"This server does not allow the model '{model}' for '{provider}'. Allowed: {', '.join(models)}.")


def ollama_model_management_allowed() -> bool:
    """Installing or removing Ollama models changes the whole server.

    COPYLOT_OLLAMA_MODEL_MANAGEMENT decides; without it, management is allowed
    on a local desktop run and refused on any deployment with tool passwords,
    a viewer or a viewer portal, where the operator manages models instead.
    """
    raw = str(os.getenv("COPYLOT_OLLAMA_MODEL_MANAGEMENT", "")).strip()
    if raw:
        return env_flag("COPYLOT_OLLAMA_MODEL_MANAGEMENT")
    return not any(env_flag(name) for name in (
        "COPYLOT_TOOL_ACCESS_ENABLED", "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED"))


def ai_operator_policy() -> dict[str, object]:
    return {"providers": allowed_ai_providers(), "models": allowed_ai_models(),
            "modelManagement": ollama_model_management_allowed()}


def local_server_models(endpoint: str | None = None, api_key: str | None = None):
    from app.services import local_ai_server

    return local_ai_server.server_models(endpoint, api_key)


def provider_default_models() -> dict[str, str]:
    """The default model for each cloud provider, after any environment override."""
    return {
        provider: (str(os.getenv(f"COPYLOT_DEFAULT_{provider.upper()}_MODEL", "")).strip() or model)
        for provider, model in _PROVIDER_DEFAULT_MODELS.items()
    }


def _default_model_for_provider(provider: ChatProvider) -> str:
    return provider_default_models().get(provider, "")


def _resolve_chat_model(payload: ChatRequest, provider: ChatProvider) -> str:
    if provider == "ollama":
        return _resolve_model(payload.model, payload.ollamaUrl)
    if provider == "openai_compatible":
        return _resolve_local_server_model(payload)
    chosen = str(payload.model or "").strip()
    if chosen:
        return chosen
    return _default_model_for_provider(provider)


def _resolve_local_server_model(payload: ChatRequest) -> str:
    from app.services import local_ai_server

    chosen = str(payload.model or "").strip()
    if chosen:
        return chosen
    listed = local_ai_server.server_models(payload.localServerUrl, payload.apiKey)
    if listed.selectedModel:
        return listed.selectedModel
    raise ValueError(listed.warnings[0] if listed.warnings else "No model is selected for the local AI server.")


def _resolve_api_key(payload: ChatRequest, provider: ChatProvider) -> str:
    """Resolve the provider API key, preferring the server environment.

    A key set on the server never leaves it. A key entered in the interface
    travels browser -> backend on every request, so it is exposed to anything
    that logs request bodies and to plain-HTTP deployments. The environment is
    therefore checked first: configuring the server makes the browser field
    irrelevant, and a stale or leaked client-side key cannot override it.
    The field is still accepted, because the UI offers it and removing it would
    break single-user installs that have no server configuration.
    """
    if provider in LOCAL_PROVIDERS:
        return ""
    env_name = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "ollama": "",
    }[provider]
    env_key = str(os.getenv(env_name, "")).strip()
    if env_key:
        return env_key
    payload_key = str(payload.apiKey or "").strip()
    if payload_key:
        return payload_key
    provider_label = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google Gemini"}[provider]
    raise ValueError(
        f"{provider_label} API key is required. Set {env_name} on the server, "
        "or enter a key in the chat settings."
    )


def _normalize_ollama_endpoint(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        text = f"http://{text}"
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Ollama endpoint must use http or https.")
    if not parsed.hostname:
        raise ValueError("Ollama endpoint must include a hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Ollama endpoint must not contain embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Ollama endpoint must not contain a query string or fragment.")

    normalized_host = parsed.hostname.lower().rstrip(".")
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    configured_values = [
        str(os.getenv("COPYLOT_OLLAMA_URL", "")).strip(),
        *str(os.getenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", "")).split(","),
    ]
    allowed_origins: set[tuple[str, str, int | None]] = set()
    for configured in configured_values:
        configured = configured.strip()
        if not configured:
            continue
        if not configured.lower().startswith(("http://", "https://")):
            configured = f"http://{configured}"
        configured_url = urllib.parse.urlsplit(configured)
        if configured_url.hostname:
            allowed_origins.add(
                (
                    configured_url.scheme.lower(),
                    configured_url.hostname.lower().rstrip("."),
                    configured_url.port,
                )
            )

    requested_origin = (parsed.scheme.lower(), normalized_host, parsed.port)
    if requested_origin not in allowed_origins:
        if normalized_host not in allowed_hosts:
            raise ValueError(
                "This Ollama server is not permitted."
            )
        # Loopback is allowed implicitly, but only Ollama's own port: the
        # server makes requests to this address on the client's behalf, and
        # "any port on localhost" would reach every other local service.
        if parsed.port != _OLLAMA_DEFAULT_PORT:
            raise ValueError(
                f"A local Ollama endpoint must use port {_OLLAMA_DEFAULT_PORT}. Other ports need "
                "COPYLOT_OLLAMA_ALLOWED_ENDPOINTS."
            )
    path = parsed.path.rstrip("/")
    if path and not path.startswith("/api/"):
        raise ValueError("Ollama endpoint path must be empty or start with /api/.")
    return urllib.parse.urlunsplit(parsed)


def _resolve_model(payload_model: str | None, endpoint_override: str | None = None) -> str:
    env_model = "" if endpoint_override else str(os.getenv("COPYLOT_OLLAMA_MODEL", "")).strip()
    if env_model:
        return env_model
    chosen = str(payload_model or "").strip()
    if chosen:
        return chosen
    models = ollama_models(endpoint_override=endpoint_override)
    if models.selectedModel:
        return models.selectedModel
    if models.warnings:
        raise ValueError(models.warnings[0])
    raise ValueError(
        "No Ollama model is selected and no installed models were detected. "
        "Pull/install a model in Ollama and select it in the chatbot."
    )


def _resolve_endpoint(endpoint_override: str | None = None) -> str:
    override = _normalize_ollama_endpoint(endpoint_override)
    if override:
        value = override.rstrip("/")
        lowered = value.lower()
        for suffix in ("/api/chat", "/api/generate"):
            if lowered.endswith(suffix):
                value = value[: -len(suffix)]
                lowered = value.lower()
                break
        if "/api/" in lowered:
            value = value.split("/api/", 1)[0]
        return f"{value.rstrip('/')}/api/chat"
    return str(os.getenv("COPYLOT_OLLAMA_URL", "")).strip() or _DEFAULT_OLLAMA_URL


def _resolve_ollama_base_url(endpoint_override: str | None = None) -> str:
    endpoint = _resolve_endpoint(endpoint_override).strip()
    while endpoint.endswith("/"):
        endpoint = endpoint[:-1]
    for suffix in ("/api/chat", "/api/generate"):
        if endpoint.endswith(suffix):
            endpoint = endpoint[: -len(suffix)]
            break
    api_marker = "/api/"
    if api_marker in endpoint:
        endpoint = endpoint.split(api_marker, 1)[0]
    return endpoint.rstrip("/")


def _is_local_ollama_endpoint(endpoint_override: str | None = None) -> bool:
    host = (urllib.parse.urlsplit(_resolve_ollama_base_url(endpoint_override)).hostname or "").lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _fetch_ollama_models_uncached(endpoint_override: str | None = None) -> list[str]:
    base_url = _resolve_ollama_base_url(endpoint_override)
    endpoint = f"{base_url}/api/tags"
    request = urllib.request.Request(endpoint, method="GET")
    response = _open_provider_request(request, timeout=12)

    with response:
        payload = _read_provider_body(response).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(payload)
    except Exception as exc:
        raise ValueError("Ollama model list returned invalid JSON.") from exc

    raw_models = parsed.get("models") if isinstance(parsed, dict) else None
    if not isinstance(raw_models, list):
        return []
    names: list[str] = []
    for item in raw_models:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
        else:
            name = str(item or "").strip()
        normalized_name = name.lower()
        is_embedding_only = any(
            marker in normalized_name
            for marker in ("embedding", "embed-", "embed:", "nomic-embed", "all-minilm", "bge-")
        )
        if name and not is_embedding_only:
            names.append(name)
    return list(dict.fromkeys(names))


def _ollama_available_models(endpoint_override: str | None = None) -> list[str]:
    cache_key = _resolve_ollama_base_url(endpoint_override) or "default"
    hit, generation = _cache_get(_MODELS_CACHE, cache_key, _MODELS_CACHE_TTL_SECONDS)
    if hit is not None:
        return hit
    names = _fetch_ollama_models_uncached(endpoint_override)
    _cache_put(_MODELS_CACHE, cache_key, names, generation)
    return names


def _invalidate_models_cache(endpoint_override: str | None = None) -> None:
    global _CACHE_GENERATION
    cache_key = _resolve_ollama_base_url(endpoint_override) or "default"
    with _CACHE_LOCK:
        _CACHE_GENERATION += 1
        _MODELS_CACHE.pop(cache_key, None)
        prefix = f"ollama|{cache_key}|"
        for key in [k for k in _MODEL_CAPABILITY_CACHE if k.startswith(prefix)]:
            del _MODEL_CAPABILITY_CACHE[key]


def ollama_models(endpoint_override: str | None = None) -> OllamaModelsResponse:
    warnings: list[str] = []
    try:
        models = _ollama_available_models(endpoint_override)
    except ValueError as exc:
        models = []
        warnings.append(str(exc))

    env_model = "" if endpoint_override else str(os.getenv("COPYLOT_OLLAMA_MODEL", "")).strip()
    selected_model: str | None
    if env_model:
        selected_model = env_model
        if models and env_model not in models:
            warnings.append(
                f"COPYLOT_OLLAMA_MODEL is set to '{env_model}', which is not currently reported by Ollama tags."
            )
    else:
        selected_model = models[0] if models else None

    if not models and not warnings:
        warnings.append("No installed Ollama models detected.")

    return OllamaModelsResponse(
        models=models,
        selectedModel=selected_model,
        warnings=warnings,
    )


def _number_from_parameter_size(value: object) -> float | None:
    text = str(value or "").strip().upper().replace(" ", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([BM])", text)
    if not match:
        return None
    number = float(match.group(1))
    return number if match.group(2) == "B" else number / 1000.0


def _ollama_model_metadata(model: str, endpoint_override: str | None = None) -> dict[str, object]:
    base_url = _resolve_ollama_base_url(endpoint_override)
    endpoint = f"{base_url}/api/show"
    body = json.dumps({"model": model}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    response = _open_provider_request(request, timeout=12)
    with response:
        raw = _read_provider_body(response).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        raise ValueError("Ollama model metadata returned invalid JSON.") from exc
    return parsed if isinstance(parsed, dict) else {}


def _model_name_parameter_count(model: str) -> float | None:
    match = re.search(r"(?:^|[:_-])(\d+(?:\.\d+)?)b(?:$|[_-])", str(model or "").lower())
    return float(match.group(1)) if match else None


def model_capability(
    provider: ChatProvider,
    model: str,
    endpoint_override: str | None = None,
) -> ModelCapabilityResponse:
    model_name = str(model or "").strip()
    if not model_name:
        raise ValueError("A model must be selected before its capabilities can be detected.")
    endpoint_key = (_resolve_ollama_base_url(endpoint_override) if provider == "ollama"
                    else str(endpoint_override or "") if provider == "openai_compatible" else "")
    cache_key = f"{provider}|{endpoint_key}|{model_name}"
    cached, generation = _cache_get(_MODEL_CAPABILITY_CACHE, cache_key, _MODEL_CAPABILITY_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    context_window: int | None = None
    parameter_count_b: float | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    source: str = "fallback"

    metadata = {}
    metadata_found: dict = {}
    if provider == "ollama":
        try:
            metadata = _ollama_model_metadata(model_name, endpoint_override)
            model_info = metadata.get("model_info")
            model_info = model_info if isinstance(model_info, dict) else {}
            context_values = [
                value
                for key, value in model_info.items()
                if str(key).lower().endswith("context_length") and isinstance(value, (int, float))
            ]
            if context_values:
                context_window = int(max(context_values))
            parameter_values = [
                value
                for key, value in model_info.items()
                if str(key).lower().endswith("parameter_count") and isinstance(value, (int, float))
            ]
            if parameter_values:
                parameter_count_b = float(max(parameter_values)) / 1_000_000_000.0
            details = metadata.get("details")
            if parameter_count_b is None and isinstance(details, dict):
                parameter_count_b = _number_from_parameter_size(details.get("parameter_size"))
            capabilities = metadata.get("capabilities")
            if isinstance(capabilities, list):
                normalized_capabilities = {str(item).strip().lower() for item in capabilities}
                supports_tools = "tools" in normalized_capabilities
                supports_vision = "vision" in normalized_capabilities
            source = "metadata"
        except ValueError:
            parameter_count_b = _model_name_parameter_count(model_name)
            source = "model_name" if parameter_count_b is not None else "fallback"
        if parameter_count_b is None:
            parameter_count_b = _model_name_parameter_count(model_name)
            if source == "fallback" and parameter_count_b is not None:
                source = "model_name"
    elif provider == "openai_compatible":
        from app.services import local_ai_server

        # llama.cpp reports the parameter count and image support; others may
        # not, and then the model's name is all there is.
        metadata_found = local_ai_server.model_metadata(endpoint_override, model_name)
        context_window = metadata_found.get("context") or local_ai_server.context_tokens(endpoint_override)
        parameter_count_b = metadata_found.get("params_b")
        supports_vision = metadata_found.get("vision")
        source = "metadata" if parameter_count_b is not None else "fallback"
        if parameter_count_b is None:
            parameter_count_b = _model_name_parameter_count(model_name)
            source = "model_name" if parameter_count_b is not None else "fallback"
    quantization = str(metadata.get("details", {}).get("quantization_level", "")) if provider == "ollama" and isinstance(metadata.get("details"), dict) else ""
    context_tier, assessment, reason = classify_model(provider, model_name, parameter_count_b, context_window, supports_tools, quantization)
    level = {"compact": 1, "standard": 2, "extended": 3}[context_tier]
    label = {1: "Low", 2: "Medium", 3: "High"}[level]
    thinks = reasoning_model(provider, model_name) or bool(
        provider == "openai_compatible" and metadata_found.get("reasoning"))
    result = ModelCapabilityResponse(
        provider=provider,
        model=model_name,
        level=level,  # type: ignore[arg-type]
        label=label,  # type: ignore[arg-type]
        contextTier=context_tier,  # type: ignore[arg-type]
        contextWindow=context_window,
        parameterCountB=round(parameter_count_b, 2) if parameter_count_b is not None else None,
        supportsTools=supports_tools,
        supportsVision=supports_vision,
        source=source,  # type: ignore[arg-type]
        assessment=assessment,
        reason=reason,
        levelName=LEVEL_NAMES[context_tier],  # type: ignore[arg-type]
        reasoning=thinks,
        outputTokens=output_tokens(context_tier, thinks, context_window),
    )
    _cache_put(_MODEL_CAPABILITY_CACHE, cache_key, result, generation)
    return result


def _run_bounded_command(args, *, env, timeout) -> str:
    limit = max(1, env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024))
    output = bytearray()
    deadline = min(provider_deadline.get() or time.monotonic() + timeout, time.monotonic() + timeout)
    if time.monotonic() >= deadline:
        raise ValueError("Model command exceeded its time limit.")
    with subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        try:
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError("Model command exceeded its time limit.")
                available = _pipe_available(process.stdout)
                if available:
                    chunk = os.read(process.stdout.fileno(), min(available, limit - len(output) + 1))
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > limit:
                        raise ValueError("Model command output exceeds the configured size limit.")
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.01)
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise ValueError("Model command exceeded its time limit.") from None
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        if process.returncode != 0:
            raise ValueError(f"Model command failed (exit code {process.returncode}).")
    return output.decode("utf-8", errors="replace").strip()


def _pipe_available(pipe) -> int:
    if os.name == "nt":
        import ctypes
        import msvcrt

        available = ctypes.c_ulong()
        handle = ctypes.c_void_p(msvcrt.get_osfhandle(pipe.fileno()))
        if not ctypes.windll.kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            if ctypes.windll.kernel32.GetLastError() in {109, 232}:
                return 0
            raise ctypes.WinError()
        return available.value
    import select

    return 65536 if select.select([pipe], [], [], 0)[0] else 0


def _run_ollama_model_command(command: str, model_name: str, endpoint_override: str | None = None) -> str:
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        raise ValueError("Ollama CLI was not found on PATH.")
    timeout_seconds = max(30, env_int("COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT", _DEFAULT_MODEL_MANAGE_TIMEOUT_SECONDS))
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _resolve_ollama_base_url(endpoint_override)
    return _run_bounded_command(
        [ollama_bin, command, model_name],
        timeout=timeout_seconds,
        env=env,
    )


def _ollama_http_manage_model(action: str, model_name: str, endpoint_override: str) -> str:
    base_url = _resolve_ollama_base_url(endpoint_override)
    if action == "install":
        endpoint = f"{base_url}/api/pull"
        method = "POST"
        body: dict[str, object] = {"name": model_name, "stream": False}
    else:
        endpoint = f"{base_url}/api/delete"
        method = "DELETE"
        body = {"name": model_name}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    response = _open_provider_request(request, timeout=max(30, env_int("COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT", _DEFAULT_MODEL_MANAGE_TIMEOUT_SECONDS)))
    with response:
        payload = _read_provider_body(response).decode("utf-8", errors="replace").strip()
    return payload


def _validated_model_name(model_name: str) -> str:
    """A model name Ollama would accept, and nothing the CLI could read as an option."""
    model = str(model_name or "").strip()
    if not model:
        raise ValueError("Model name cannot be empty.")
    if len(model) > 200 or not _OLLAMA_MODEL_NAME.match(model):
        raise ValueError(
            "Model name may contain letters, digits, '.', '_', '-', '/' and one ':tag' "
            "(for example llama3.1:8b)."
        )
    return model


def ollama_install_model(model_name: str, endpoint_override: str | None = None) -> OllamaModelManageResponse:
    model = _validated_model_name(model_name)
    output = (
        _ollama_http_manage_model("install", model, endpoint_override)
        if endpoint_override
        else _run_ollama_model_command("pull", model, endpoint_override)
    )
    _invalidate_models_cache(endpoint_override)
    refreshed = ollama_models(endpoint_override=endpoint_override)
    detail = f"Installed model '{model}'."
    if output:
        detail = f"{detail} {output}"
    return OllamaModelManageResponse(
        ok=True,
        action="install",
        model=model,
        detail=detail,
        models=refreshed.models,
        selectedModel=refreshed.selectedModel,
        warnings=refreshed.warnings,
    )


def ollama_remove_model(model_name: str, endpoint_override: str | None = None) -> OllamaModelManageResponse:
    model = _validated_model_name(model_name)
    output = (
        _ollama_http_manage_model("remove", model, endpoint_override)
        if endpoint_override
        else _run_ollama_model_command("rm", model, endpoint_override)
    )
    _invalidate_models_cache(endpoint_override)
    refreshed = ollama_models(endpoint_override=endpoint_override)
    detail = f"Removed model '{model}'."
    if output:
        detail = f"{detail} {output}"
    return OllamaModelManageResponse(
        ok=True,
        action="remove",
        model=model,
        detail=detail,
        models=refreshed.models,
        selectedModel=refreshed.selectedModel,
        warnings=refreshed.warnings,
    )


def _detect_gpu_status_uncached(endpoint_override: str | None = None) -> OllamaGpuStatusResponse:
    if not _is_local_ollama_endpoint(endpoint_override):
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="remote",
            deviceName=None,
            reason="Acceleration status is unknown for remote Ollama endpoints; managed by host.",
            remoteEndpoint=True,
            acceleration="unknown",
        )
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider=None,
            deviceName=None,
            reason="No compatible CUDA GPU detected (nvidia-smi not found).",
            remoteEndpoint=False,
            acceleration="cpu",
        )
    try:
        process = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except Exception as exc:
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="cuda",
            deviceName=None,
            reason=f"GPU detection failed: {exc}",
            remoteEndpoint=False,
            acceleration="unknown",
        )
    if process.returncode != 0:
        stderr = str(process.stderr or "").strip()
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="cuda",
            deviceName=None,
            reason=stderr or "No eligible CUDA GPU reported by nvidia-smi.",
            remoteEndpoint=False,
            acceleration="cpu",
        )
    names = [line.strip() for line in str(process.stdout or "").splitlines() if line.strip()]
    if not names:
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="cuda",
            deviceName=None,
            reason="No eligible CUDA GPU reported by nvidia-smi.",
            remoteEndpoint=False,
            acceleration="cpu",
        )
    return OllamaGpuStatusResponse(
        gpuEligible=True,
        gpuEnabledDefault=env_flag("COPYLOT_OLLAMA_GPU_DEFAULT", True),
        provider="cuda",
        deviceName=names[0],
        reason=None,
        remoteEndpoint=False,
        acceleration="gpu",
    )


def ollama_gpu_status(endpoint_override: str | None = None) -> OllamaGpuStatusResponse:
    cache_key = _resolve_ollama_base_url(endpoint_override) or "default"
    hit, generation = _cache_get(_GPU_STATUS_CACHE, cache_key, _GPU_STATUS_CACHE_TTL_SECONDS)
    if hit is not None:
        return hit
    payload = _detect_gpu_status_uncached(cache_key)
    _cache_put(_GPU_STATUS_CACHE, cache_key, payload, generation)
    return payload


def _resolve_gpu_enabled(payload_gpu_enabled: bool | None, endpoint_override: str | None = None) -> bool:
    status = ollama_gpu_status(endpoint_override)
    if not status.gpuEligible:
        return False
    if payload_gpu_enabled is None:
        return bool(status.gpuEnabledDefault)
    return bool(payload_gpu_enabled)


def _validate_cloud_analysis_context(value: str) -> str:
    context = str(value or "").strip()
    if len(context) > _CLOUD_MAX_CONTEXT_CHARS:
        raise ValueError(
            f"Generated cloud AI context exceeds {_CLOUD_MAX_CONTEXT_CHARS:,} characters. "
            "Use a more compact evidence profile."
        )
    if any(pattern.search(context) for pattern in _PROTECTED_CONTEXT_PATTERNS):
        raise ValueError(
            "Generated AI context contains a protected path or credential-like value and was not sent."
        )
    return context


def _open_ollama_request(
    payload: ChatRequest,
    *,
    messages: list[dict[str, str]],
    output_schema: dict | None = None,
    num_ctx: int | None = None,
    num_predict: int = 1024,
    image: str | None = None,
):
    endpoint_override = payload.ollamaUrl
    model = _resolve_model(payload.model, endpoint_override)
    endpoint = _resolve_endpoint(endpoint_override)
    messages = [
        {"role": str(item.get("role", "")).strip(), "content": str(item.get("content", ""))}
        for item in messages
        if str(item.get("role", "")).strip() and str(item.get("content", "")).strip()
    ]
    if not messages:
        raise ValueError("Chat request has no valid messages.")
    is_remote_endpoint = not _is_local_ollama_endpoint(endpoint)
    requested_num_gpu = env_int("COPYLOT_OLLAMA_NUM_GPU", -1)
    num_gpu: int | None
    if is_remote_endpoint:
        # For remote Ollama, do not force GPU/CPU from the client host.
        # Let the remote Ollama host apply its own runtime defaults.
        num_gpu = None
    else:
        gpu_enabled = _resolve_gpu_enabled(payload.gpuEnabled, endpoint_override)
        num_gpu = requested_num_gpu if gpu_enabled else 0

    options: dict[str, float | int] = {
        "temperature": 0,
        "top_p": env_float("COPYLOT_OLLAMA_TOP_P", 0.9),
        "num_predict": num_predict,
        "num_ctx": int(num_ctx or _ollama_context_floor()),
        "repeat_penalty": env_float("COPYLOT_OLLAMA_REPEAT_PENALTY", 1.1),
    }
    if num_gpu is not None:
        options["num_gpu"] = num_gpu

    if image and messages and messages[-1]["role"] == "user":
        messages[-1] = {**messages[-1], "images": [image.split(",", 1)[1]]}  # type: ignore[dict-item]
    request_body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": env_flag("COPYLOT_OLLAMA_THINK", False),
        "options": options,
    }
    if output_schema is not None:
        request_body["format"] = output_schema
    request_bytes = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=request_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    response = _open_provider_request(request, timeout=_provider_call_timeout())
    return model, response


def _extract_system_and_dialogue(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    system_parts: list[str] = []
    dialogue: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            continue
        dialogue.append({"role": role, "content": content})
    return "\n\n".join(system_parts).strip(), dialogue


def _openai_content_to_text(content: object) -> str:
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


def _read_json_response(response, invalid_json_message: str) -> dict[str, object]:
    with response:
        payload = _read_provider_body(response).decode("utf-8", errors="replace")
    try:
        parsed = json.loads(payload)
    except Exception as exc:
        raise ValueError(invalid_json_message) from exc
    if not isinstance(parsed, dict):
        raise ValueError(invalid_json_message)
    return parsed


def _provider_call_timeout() -> float:
    """Seconds one model reply may take (`COPYLOT_AI_CALL_TIMEOUT`, default 300)."""
    return float(env_int("COPYLOT_AI_CALL_TIMEOUT", 300, minimum=30))


def _with_image(messages: list[dict[str, str]], image: str | None, part) -> list[dict]:
    """The last user message with the plot image added in the provider's format."""
    sent: list[dict] = [dict(message) for message in messages]
    if image and sent and sent[-1].get("role") == "user":
        sent[-1]["content"] = part(str(sent[-1]["content"]), image)
    return sent


def _openai_chat_text(
    *,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    image: str | None = None,
) -> str:
    request_body: dict[str, object] = {
        "model": model,
        "messages": _with_image(messages, image, lambda text, url: [
            {"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]),
        # max_completion_tokens is accepted by every current chat model and is the
        # only limit reasoning models (o-series, GPT-5) accept.
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    if not reasoning_model("openai", model):
        request_body["temperature"] = temperature
    request = urllib.request.Request(
        _OPENAI_CHAT_ENDPOINT,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    response = _open_provider_request(request, timeout=_provider_call_timeout(), provider="OpenAI")
    parsed = _read_json_response(response, "OpenAI returned invalid JSON.")
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI response did not contain choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("OpenAI response choice format is invalid.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenAI response did not include a message.")
    text = _openai_content_to_text(message.get("content"))
    if not text.strip():
        raise ValueError("OpenAI response was empty.")
    return text


def _anthropic_chat_text(
    *,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    image: str | None = None,
) -> str:
    system_text, dialogue = _extract_system_and_dialogue(messages)
    request_body: dict[str, object] = {
        "model": model,
        "messages": _with_image(dialogue, image, lambda text, url: [
            {"type": "image", "source": {"type": "base64", "media_type": url[5:url.index(";")],
                                         "data": url.split(",", 1)[1]}},
            {"type": "text", "text": text}]),
        "max_tokens": max_tokens,
    }
    # Use provider defaults: recent Anthropic models reject sampling overrides.
    if system_text:
        request_body["system"] = system_text
    request = urllib.request.Request(
        _ANTHROPIC_MESSAGES_ENDPOINT,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    response = _open_provider_request(request, timeout=_provider_call_timeout(), provider="Anthropic")
    parsed = _read_json_response(response, "Anthropic returned invalid JSON.")
    blocks = parsed.get("content")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("Anthropic response did not include content.")
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type", "")).strip().lower() != "text":
            continue
        text = str(block.get("text", "")).strip()
        if text:
            texts.append(text)
    merged = "\n".join(texts).strip()
    if not merged:
        raise ValueError("Anthropic response was empty.")
    return merged


def _gemini_chat_text(
    *,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    image: str | None = None,
) -> str:
    system_text, dialogue = _extract_system_and_dialogue(messages)
    contents: list[dict[str, object]] = []
    for item in dialogue:
        role = str(item.get("role", "")).strip().lower()
        text = str(item.get("content", "")).strip()
        if not text:
            continue
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            }
        )
    if image and contents and contents[-1]["role"] == "user":
        contents[-1]["parts"] = [*contents[-1]["parts"], {"inline_data": {  # type: ignore[misc]
            "mime_type": image[5:image.index(";")], "data": image.split(",", 1)[1]}}]
    request_body: dict[str, object] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_text:
        request_body["systemInstruction"] = {"parts": [{"text": system_text}]}
    model_path = urllib.parse.quote(model, safe="")
    endpoint = f"{_GEMINI_BASE_ENDPOINT}/{model_path}:generateContent"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    response = _open_provider_request(request, timeout=_provider_call_timeout(), provider="Gemini")
    parsed = _read_json_response(response, "Gemini returned invalid JSON.")
    candidates = parsed.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response did not include candidates.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise ValueError("Gemini candidate format is invalid.")
    content = first.get("content")
    if not isinstance(content, dict):
        raise ValueError("Gemini response did not include content.")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ValueError("Gemini response did not include text parts.")
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text", "")).strip()
        if text:
            texts.append(text)
    merged = "\n".join(texts).strip()
    if not merged:
        raise ValueError("Gemini response was empty.")
    return merged


# --- Context budget -------------------------------------------------------
# Iteration 21 (2026-09-21): with a fixed num_ctx of 8192, styling/compound
# planner prompts reached 7.2k-8.2k tokens and three replies stopped exactly at
# the window (8163+29, 8164+28, 8145+47 tokens): truncated JSON, reported as an
# "invalid plan". The window is now sized per request from a conservative
# estimate, between a floor (unchanged 8192 default, so ordinary requests do
# not reload the model) and a ceiling that the owner sets for their hardware
# and that never exceeds the model's own trained window. The planner trims
# irrelevant controls to fit the floor first (see scientific_assistant), so
# the ceiling is headroom, not the normal case.
# JSON-dense prompts (control ids, enums) measured 3.8-4.7 characters per
# token in the iteration-21 logs across all eight models; 3.3 over-estimates on
# purpose; actual token counts are still checked because this is only an estimate.
_CHARS_PER_TOKEN = 3.3
# Reserve the full generation limit plus framing headroom; token sizing is an estimate.
ASSISTANT_OUTPUT_RESERVE = 1024 + 128
_CLOUD_PROMPT_TOKENS = 100_000
_NUM_CTX_IN_USE: dict[str, int] = {}
_NUM_CTX_LOCK = Lock()


class AssistantContextExhausted(ValueError):
    """The request and reply do not fit the model's context window."""


def estimate_tokens(*texts: str) -> int:
    return math.ceil(sum(len(text or "") for text in texts) / _CHARS_PER_TOKEN)


def _ollama_context_floor() -> int:
    return max(2048, env_int("COPYLOT_OLLAMA_NUM_CTX", 8192))


def _ollama_context_limits(model: str, endpoint_override: str | None = None) -> tuple[int, int]:
    """(floor, ceiling) num_ctx for this Ollama model."""
    floor = _ollama_context_floor()
    ceiling = max(floor, env_int("COPYLOT_OLLAMA_MAX_CTX", 16384))
    if not model:
        return floor, ceiling
    try:
        capability = model_capability("ollama", model, endpoint_override)
        window = capability.contextWindow
        tier, size = getattr(capability, "contextTier", "compact"), getattr(capability, "parameterCountB", None)
    except Exception:  # metadata is an optimisation; the env bounds still apply
        window, tier, size = None, "compact", None
    # Iteration 22: qwen3-coder (30B) and qwen3.6:35b loaded at 8192, then
    # reloaded at 12288 (21 s / 29 s) as soon as their full-panel styling prompt
    # arrived; every other model stayed at 8192 for the whole run. Large models
    # that also see the full panel start at the larger window. The 12B models
    # did not need it and keep 8192, so their VRAM use is unchanged.
    if tier != "compact" and size is not None and size >= env_float("COPYLOT_OLLAMA_LARGE_MODEL_B", 20.0):
        floor = max(floor, env_int("COPYLOT_OLLAMA_LARGE_NUM_CTX", 12288))
    if window:
        ceiling = min(ceiling, int(window))
    floor = min(floor, ceiling)
    return floor, ceiling


def assistant_profile(payload: ChatRequest) -> str:
    """The planner profile for this request: the user's level, else the model's."""
    chosen = LEVELS.get(getattr(payload, "assistantLevel", "auto") or "auto")
    if chosen:
        return chosen
    provider = _resolve_provider(payload.provider)
    try:
        model = _resolve_chat_model(payload, provider) if provider != "ollama" else _resolve_model(payload.model, payload.ollamaUrl)
        endpoint = payload.ollamaUrl if provider == "ollama" else payload.localServerUrl
        return model_capability(provider, model, endpoint).contextTier
    except Exception:  # the profile is an optimisation; the safe level still works
        return "compact"


def assistant_output_tokens(payload: ChatRequest) -> int:
    """Reply budget for this request: its level's room plus thinking room for reasoning models."""
    provider = _resolve_provider(payload.provider)
    profile = assistant_profile(payload)
    try:
        model = _resolve_chat_model(payload, provider) if provider != "ollama" else _resolve_model(payload.model, payload.ollamaUrl)
        endpoint = payload.ollamaUrl if provider == "ollama" else payload.localServerUrl
        capability = model_capability(provider, model, endpoint)
        thinks, window = bool(getattr(capability, "reasoning", False)), capability.contextWindow
    except Exception:
        thinks, window = False, None
    return output_tokens(profile, thinks, window)


def assistant_input_limit(payload: ChatRequest) -> int:
    """Characters one prompt may carry: 24,000, more for an Advanced model with a large window."""
    provider = _resolve_provider(payload.provider)
    try:
        model = _resolve_chat_model(payload, provider) if provider != "ollama" else _resolve_model(payload.model, payload.ollamaUrl)
        endpoint = payload.ollamaUrl if provider == "ollama" else payload.localServerUrl
        window = model_capability(provider, model, endpoint).contextWindow
    except Exception:
        window = None
    return input_limit(assistant_profile(payload), window)


def assistant_output_reserve(payload: ChatRequest) -> int:
    return assistant_output_tokens(payload) + 128


def assistant_prompt_budget(payload: ChatRequest) -> tuple[int, int]:
    """(preferred, maximum) prompt tokens for this provider/model, reply reserve excluded.

    The planner fits the preferred budget by leaving out controls unrelated to
    the question; the maximum is what a larger window can absorb when the
    relevant controls alone do not fit. Cloud models have large windows; their
    size is still bounded by ASSISTANT_INPUT_MAX_CHARS.
    """
    provider = _resolve_provider(payload.provider)
    if provider == "openai_compatible":
        from app.services import local_ai_server

        window = local_ai_server.context_tokens(payload.localServerUrl, payload.apiKey)
        reserve = assistant_output_reserve(payload)
        return window - reserve, window - reserve
    if provider != "ollama":
        return _CLOUD_PROMPT_TOKENS, _CLOUD_PROMPT_TOKENS
    try:
        model = _resolve_model(payload.model, payload.ollamaUrl)
    except ValueError:
        model = ""
    floor, ceiling = _ollama_context_limits(model, payload.ollamaUrl)
    reserve = assistant_output_reserve(payload)
    return floor - reserve, ceiling - reserve


def _ollama_num_ctx(model: str, endpoint_override: str | None, prompt_tokens: int,
                    reserve: int = ASSISTANT_OUTPUT_RESERVE) -> int:
    floor, ceiling = _ollama_context_limits(model, endpoint_override)
    needed = prompt_tokens + reserve
    key = f"{_resolve_ollama_base_url(endpoint_override)}|{model}"
    if needed <= floor:
        with _NUM_CTX_LOCK:
            return max(floor, min(ceiling, _NUM_CTX_IN_USE.get(key, 0)))
    if needed > ceiling:
        raise AssistantContextExhausted(
            f"This request needs about {needed} tokens but the selected model's context is limited to {ceiling}. "
            "Nothing was changed. Ask a narrower question, collapse the advanced plot options, or raise "
            "COPYLOT_OLLAMA_MAX_CTX if the model and hardware allow it.")
    # Whole 4096-token steps, and never shrinking below the window a model
    # already runs with, keep reloads rare: Ollama reloads a model for every new
    # num_ctx, which costs seconds on large models.
    with _NUM_CTX_LOCK:
        chosen = max(min(ceiling, -(-needed // 4096) * 4096), min(ceiling, _NUM_CTX_IN_USE.get(key, 0)))
        _NUM_CTX_IN_USE[key] = chosen
    return chosen


def assistant_completion(payload: ChatRequest, instruction: str, data: str, *, schema=None,
                         image: str | None = None, effort: str | None = None) -> tuple[str, str]:
    """Bounded completion for the assistant's planner or evidence explanation.

    The reply budget follows the model's level and whether it thinks first
    (`assistant_output_tokens`). ``image`` (a data URL of the rendered plot)
    goes with the user message to providers that accept images."""
    from app.services import assistant_progress

    provider = _resolve_provider(payload.provider)
    max_tokens = assistant_output_tokens(payload)
    reserve = max_tokens + 128
    require_cloud_ai_consent(provider)
    assistant_progress.update(getattr(payload, "progressId", None), "waiting")
    assistant_progress.next_call(getattr(payload, "progressId", None))
    if len(data) > assistant_input_limit(payload):
        raise ValueError("This assistant request is too large. Ask a shorter, more focused question.")
    if provider not in LOCAL_PROVIDERS:
        # The instruction carries generated context too (controls, labels), so
        # both messages are checked before anything leaves the machine.
        _validate_cloud_analysis_context(instruction)
        _validate_cloud_analysis_context(data)
    messages = [{"role": "system", "content": instruction}, {"role": "user", "content": data}]
    if provider == "ollama":
        try:
            model_name = _resolve_model(payload.model, payload.ollamaUrl)
        except ValueError:
            model_name = ""  # _open_ollama_request reports the missing model
        check_ai_operator_policy(provider, model_name)
        num_ctx = _ollama_num_ctx(model_name, payload.ollamaUrl,
                                  estimate_tokens(instruction, data), reserve)
        model, response = _open_ollama_request(
            payload, messages=messages, output_schema=schema, num_ctx=num_ctx,
            num_predict=max_tokens, image=image,
        )
        parsed = _read_json_response(response, "Ollama returned invalid JSON.")
        # Reasoning text is not an answer or an executable plan.
        message = parsed.get("message", {})
        text = message.get("content", "") if isinstance(message, dict) else ""
        used = sum(value for value in (parsed.get("prompt_eval_count"), parsed.get("eval_count"))
                   if isinstance(value, int) and not isinstance(value, bool))
        if used >= num_ctx:
            # Named separately from an incomplete answer: a model that runs into
            # the window was never given room to answer (iteration 21).
            raise AssistantContextExhausted(
                f"The request filled the model's {num_ctx}-token context window before the reply was complete. "
                "Nothing was changed. Ask a narrower question or collapse the advanced plot options.")
        if parsed.get("done_reason") == "length":
            raise ValueError(f"The model used its whole reply budget ({max_tokens} tokens) before it finished. "
                             "Nothing was changed. Ask for a smaller step.")
    elif provider == "openai_compatible":
        from app.services import local_ai_server

        model = _resolve_local_server_model(payload)
        check_ai_operator_policy(provider, model)
        window = local_ai_server.context_tokens(payload.localServerUrl, payload.apiKey)
        if estimate_tokens(instruction, data) + reserve > window:
            raise AssistantContextExhausted(
                f"This request needs about {estimate_tokens(instruction, data) + reserve} tokens "
                f"but the local AI server's context is {window}. Nothing was changed. Ask a narrower question, "
                "collapse the advanced plot options, or start the server with a larger context.")
        text = local_ai_server.chat_text(payload, messages, model=model, schema=schema, context_window=window,
                                         max_tokens=max_tokens, image=image, effort=effort)
    else:
        model = _resolve_chat_model(payload, provider)
        check_ai_operator_policy(provider, model)
        completion = {"openai": _openai_chat_text, "anthropic": _anthropic_chat_text, "gemini": _gemini_chat_text}[provider]
        text = completion(model=model, api_key=_resolve_api_key(payload, provider), messages=messages,
                          temperature=0, max_tokens=max_tokens, image=image)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The assistant returned no usable answer.")
    return model, text.strip()



class NativeToolsUnavailable(ValueError):
    """This provider or model does not take tool calls; the JSON plan is used instead."""


def native_tools_supported(payload: ChatRequest) -> bool:
    """Whether the assistant may offer this model native tools (Advanced models only, see assistant_tools)."""
    if not env_flag("COPYLOT_AI_NATIVE_TOOLS", True):
        return False
    provider = _resolve_provider(payload.provider)
    try:
        if provider == "openai_compatible":
            from app.services import local_ai_server

            model = _resolve_local_server_model(payload)
            return bool(local_ai_server.model_metadata(payload.localServerUrl, model, payload.apiKey).get("tools"))
        if provider == "ollama":
            model = _resolve_model(payload.model, payload.ollamaUrl)
            return bool(model_capability("ollama", model, payload.ollamaUrl).supportsTools)
        return provider == "openai"
    except ValueError:
        return False


def assistant_tool_turn(payload: ChatRequest, messages: list[dict], tools: list[dict], *,
                        image: str | None = None, effort: str | None = None) -> tuple[str, dict]:
    """One model turn with tools; returns (model, assistant message with any tool_calls).

    Same budget, consent, operator policy and context checks as assistant_completion."""
    from app.services import assistant_progress

    provider = _resolve_provider(payload.provider)
    require_cloud_ai_consent(provider)
    text = json.dumps(messages)
    if len(text) > assistant_input_limit(payload) * 2:
        raise ValueError("This assistant request is too large. Ask a shorter, more focused question.")
    if provider not in LOCAL_PROVIDERS:
        _validate_cloud_analysis_context(text)
    max_tokens = assistant_output_tokens(payload)
    progress = getattr(payload, "progressId", None)
    assistant_progress.update(progress, "waiting")
    assistant_progress.next_call(progress)
    if provider == "openai_compatible":
        from app.services import local_ai_server

        model = _resolve_local_server_model(payload)
        check_ai_operator_policy(provider, model)
        window = local_ai_server.context_tokens(payload.localServerUrl, payload.apiKey)
        if estimate_tokens(text) + max_tokens + 128 > window:
            raise AssistantContextExhausted(
                f"This request needs more than the local AI server's {window}-token context. Nothing was changed.")
        try:
            message = local_ai_server.chat_message(payload, messages, model=model, schema=None, context_window=window,
                                                   max_tokens=max_tokens, image=image, tools=tools, effort=effort)
        except local_ai_server.ToolsUnsupported as exc:
            raise NativeToolsUnavailable(str(exc)) from exc
        return model, message
    if provider == "ollama":
        model = _resolve_model(payload.model, payload.ollamaUrl)
        check_ai_operator_policy(provider, model)
        num_ctx = _ollama_num_ctx(model, payload.ollamaUrl, estimate_tokens(text), max_tokens + 128)
        sent = [dict(message) for message in messages]
        for message in sent:  # Ollama takes tool arguments as objects
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                if isinstance(function.get("arguments"), str):
                    function["arguments"] = json.loads(function["arguments"] or "{}")
        if image and sent and sent[-1].get("role") == "user":
            sent[-1]["images"] = [image.split(",", 1)[1]]
        body = {"model": model, "messages": sent, "tools": tools, "stream": False,
                "think": env_flag("COPYLOT_OLLAMA_THINK", False),
                "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": num_ctx}}
        request = urllib.request.Request(_resolve_endpoint(payload.ollamaUrl), data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        parsed = _read_json_response(_open_provider_request(request, timeout=_provider_call_timeout()),
                                     "Ollama returned invalid JSON.")
        message = parsed.get("message") if isinstance(parsed.get("message"), dict) else {}
        if parsed.get("done_reason") == "length":
            raise ValueError(f"The model used its whole reply budget ({max_tokens} tokens) before it finished. "
                             "Nothing was changed. Ask for a smaller step.")
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            if not isinstance(function.get("arguments"), str):
                function["arguments"] = json.dumps(function.get("arguments") or {})
        return model, message
    if provider == "openai":
        model = _resolve_chat_model(payload, provider)
        check_ai_operator_policy(provider, model)
        body = {"model": model, "messages": _with_image(messages, image, lambda content, url: [
            {"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": url}}]),
            "tools": tools, "tool_choice": "required", "max_completion_tokens": max_tokens, "stream": False}
        if not reasoning_model("openai", model):
            body["temperature"] = 0
        request = urllib.request.Request(_OPENAI_CHAT_ENDPOINT, data=json.dumps(body).encode("utf-8"), headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {_resolve_api_key(payload, provider)}"},
            method="POST")
        parsed = _read_json_response(_open_provider_request(request, timeout=_provider_call_timeout(), provider="OpenAI"),
                                     "OpenAI returned invalid JSON.")
        choices = parsed.get("choices")
        first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        if first.get("finish_reason") == "length":
            raise ValueError(f"The model used its whole reply budget ({max_tokens} tokens) before it finished. "
                             "Nothing was changed. Ask for a smaller step.")
        message = first.get("message")
        return model, message if isinstance(message, dict) else {}
    raise NativeToolsUnavailable(f"{provider} is used through the JSON plan.")

from __future__ import annotations

import json
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
from app.services.assistant_profiles import classify_model
from app.services.cloud_ai_consent import require_cloud_ai_consent
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
    limit = max(1, _env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024))
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
_DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
_DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_MESSAGES_ENDPOINT = "https://api.anthropic.com/v1/messages"
_GEMINI_BASE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
_CLOUD_MAX_CONTEXT_CHARS = 96_000
ASSISTANT_INPUT_MAX_CHARS = 24_000
_PROTECTED_CONTEXT_PATTERNS = (
    re.compile(r"(?i)(?:^|[\s'\"])(?:[a-z]:[\\/]|\\\\|file://)"),
    re.compile(r"(?i)(?:api[-_ ]?key|authorization|access[-_ ]?token|password)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def ai_mode_enabled() -> bool:
    return str(os.getenv("COPYLOT_AI_MODE", "")).strip().lower() in _TRUTHY_VALUES


def _resolve_provider(payload_provider: str | None) -> ChatProvider:
    value = str(payload_provider or "").strip().lower()
    if value in {"openai", "anthropic", "gemini", "ollama"}:
        return value
    return "ollama"


def _default_model_for_provider(provider: ChatProvider) -> str:
    if provider == "openai":
        return _DEFAULT_OPENAI_MODEL
    if provider == "anthropic":
        return _DEFAULT_ANTHROPIC_MODEL
    if provider == "gemini":
        return _DEFAULT_GEMINI_MODEL
    return ""


def _resolve_chat_model(payload: ChatRequest, provider: ChatProvider) -> str:
    if provider == "ollama":
        return _resolve_model(payload.model, payload.ollamaUrl)
    chosen = str(payload.model or "").strip()
    if chosen:
        return chosen
    return _default_model_for_provider(provider)


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
    if provider == "ollama":
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
    if normalized_host not in allowed_hosts and requested_origin not in allowed_origins:
        raise ValueError(
            "Ollama endpoint override is not allowed. Configure it with "
            "COPYLOT_OLLAMA_URL or COPYLOT_OLLAMA_ALLOWED_ENDPOINTS."
        )
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


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY_VALUES


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
    cache_key = f"{provider}|{_resolve_ollama_base_url(endpoint_override) if provider == 'ollama' else ''}|{model_name}"
    cached, generation = _cache_get(_MODEL_CAPABILITY_CACHE, cache_key, _MODEL_CAPABILITY_CACHE_TTL_SECONDS)
    if cached is not None:
        return cached

    context_window: int | None = None
    parameter_count_b: float | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    source: str = "fallback"

    metadata = {}
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
    quantization = str(metadata.get("details", {}).get("quantization_level", "")) if provider == "ollama" and isinstance(metadata.get("details"), dict) else ""
    context_tier, assessment, reason = classify_model(provider, model_name, parameter_count_b, context_window, supports_tools, quantization)
    level = {"compact": 1, "standard": 2, "extended": 3}[context_tier]
    label = {1: "Low", 2: "Medium", 3: "High"}[level]
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
    )
    _cache_put(_MODEL_CAPABILITY_CACHE, cache_key, result, generation)
    return result


def _run_bounded_command(args, *, env, timeout) -> str:
    limit = max(1, _env_int("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", 8 * 1024 * 1024))
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
    timeout_seconds = max(30, _env_int("COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT", _DEFAULT_MODEL_MANAGE_TIMEOUT_SECONDS))
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
    response = _open_provider_request(request, timeout=max(30, _env_int("COPYLOT_OLLAMA_MODEL_MANAGE_TIMEOUT", _DEFAULT_MODEL_MANAGE_TIMEOUT_SECONDS)))
    with response:
        payload = _read_provider_body(response).decode("utf-8", errors="replace").strip()
    return payload


def ollama_install_model(model_name: str, endpoint_override: str | None = None) -> OllamaModelManageResponse:
    model = str(model_name or "").strip()
    if not model:
        raise ValueError("Model name cannot be empty.")
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
    model = str(model_name or "").strip()
    if not model:
        raise ValueError("Model name cannot be empty.")
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
        gpuEnabledDefault=_env_bool("COPYLOT_OLLAMA_GPU_DEFAULT", True),
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
    requested_num_gpu = _env_int("COPYLOT_OLLAMA_NUM_GPU", -1)
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
        "top_p": _env_float("COPYLOT_OLLAMA_TOP_P", 0.9),
        "num_predict": 1024,
        "num_ctx": 8192,
        "repeat_penalty": _env_float("COPYLOT_OLLAMA_REPEAT_PENALTY", 1.1),
    }
    if num_gpu is not None:
        options["num_gpu"] = num_gpu

    request_body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": _env_bool("COPYLOT_OLLAMA_THINK", False),
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

    response = _open_provider_request(request, timeout=180)
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


def _openai_chat_text(
    *,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    request_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        _OPENAI_CHAT_ENDPOINT,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    response = _open_provider_request(request, timeout=180, provider="OpenAI")
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
) -> str:
    system_text, dialogue = _extract_system_and_dialogue(messages)
    request_body: dict[str, object] = {
        "model": model,
        "messages": dialogue,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
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
    response = _open_provider_request(request, timeout=180, provider="Anthropic")
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
    response = _open_provider_request(request, timeout=180, provider="Gemini")
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


def assistant_completion(payload: ChatRequest, instruction: str, data: str, *, schema=None) -> tuple[str, str]:
    """Bounded completion for the assistant's planner or evidence explanation."""
    provider = _resolve_provider(payload.provider)
    require_cloud_ai_consent(provider)
    if len(data) > ASSISTANT_INPUT_MAX_CHARS:
        raise ValueError("This assistant request is too large. Ask a shorter, more focused question.")
    if provider != "ollama":
        _validate_cloud_analysis_context(data)
    messages = [{"role": "system", "content": instruction}, {"role": "user", "content": data}]
    if provider == "ollama":
        model, response = _open_ollama_request(
            payload, messages=messages, output_schema=schema,
        )
        parsed = _read_json_response(response, "Ollama returned invalid JSON.")
        # Reasoning text is not an answer or an executable plan.
        message = parsed.get("message", {})
        text = message.get("content", "") if isinstance(message, dict) else ""
        if parsed.get("done_reason") == "length":
            raise ValueError("The assistant response was incomplete. Ask for a smaller step.")
    else:
        model = _resolve_chat_model(payload, provider)
        completion = {"openai": _openai_chat_text, "anthropic": _anthropic_chat_text, "gemini": _gemini_chat_text}[provider]
        text = completion(model=model, api_key=_resolve_api_key(payload, provider), messages=messages,
                          temperature=0, max_tokens=1024)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("The assistant returned no usable answer.")
    return model, text.strip()

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
import urllib.error
import urllib.request

from app.schemas.chat import (
    ChatMessage,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaGpuStatusResponse,
    OllamaModelsResponse,
)

_TRUTHY_VALUES = {"1", "true", "yes", "on"}
_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
_DEFAULT_SYSTEM_PROMPT = (
    "You are a data analysis and research assistant for proteomics workflows. "
    "Domain focus is mass-spectrometry proteomics, not DNA/RNA sequencing unless explicitly stated. "
    "Follow the workflow scope provided by module context strictly: "
    "protein workflow -> proteins only; phospho workflow -> phosphorylation sites only; "
    "peptide workflow -> peptides only; phosprot workflow -> phosphoproteins only. "
    "Do not mix these levels unless the user explicitly asks for a cross-level interpretation. "
    "Respond with short, precise answers. "
    "Use user-facing module names and avoid internal module keys or code-like identifiers in your wording. "
    "If volcano/differential context is available and the user asks for interesting proteins or targets, prioritize statistically significant features and cite direction, log2FC, and -log10 adjusted p-value. "
    "Prioritize factual correctness over speculation. "
    "If needed context is missing, ask one focused follow-up question. "
    "If you are uncertain, say so clearly and suggest how to verify."
)
_GPU_STATUS_CACHE_TTL_SECONDS = 60.0
_GPU_STATUS_CACHE: tuple[float, OllamaGpuStatusResponse] | None = None
_MODELS_CACHE_TTL_SECONDS = 30.0
_MODELS_CACHE: tuple[float, list[str]] | None = None
_DEFAULT_NUM_PREDICT = 384
_MAX_CONTINUATION_ATTEMPTS = 2
_CONTINUATION_USER_PROMPT = (
    "Continue your previous answer from exactly where it ended. "
    "Keep it short and precise. Do not repeat earlier text. Finish the thought cleanly."
)


def _normalize_message_text(message_obj: dict[str, object]) -> str:
    thinking = str(message_obj.get("thinking", ""))
    content = str(message_obj.get("content", ""))
    if thinking and content:
        return f"<think>{thinking}</think>\n{content}"
    if thinking:
        return f"<think>{thinking}</think>"
    return content


def ai_mode_enabled() -> bool:
    return str(os.getenv("COPYLOT_AI_MODE", "")).strip().lower() in _TRUTHY_VALUES


def _resolve_model(payload_model: str | None) -> str:
    env_model = str(os.getenv("COPYLOT_OLLAMA_MODEL", "")).strip()
    if env_model:
        return env_model
    chosen = str(payload_model or "").strip()
    if chosen:
        return chosen
    models = ollama_models()
    if models.selectedModel:
        return models.selectedModel
    if models.warnings:
        raise ValueError(models.warnings[0])
    raise ValueError(
        "No Ollama model is selected and no installed models were detected. "
        "Pull/install a model in Ollama and select it in the chatbot."
    )


def _resolve_endpoint() -> str:
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


def _resolve_ollama_base_url() -> str:
    endpoint = _resolve_endpoint().strip()
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


def _fetch_ollama_models_uncached() -> list[str]:
    base_url = _resolve_ollama_base_url()
    endpoint = f"{base_url}/api/tags"
    request = urllib.request.Request(endpoint, method="GET")
    try:
        response = urllib.request.urlopen(request, timeout=12)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if detail:
            raise ValueError(f"Failed to load Ollama models ({exc.code}): {detail}") from exc
        raise ValueError(f"Failed to load Ollama models (HTTP {exc.code}).") from exc
    except urllib.error.URLError as exc:
        raise ValueError(
            f"Could not reach Ollama at {endpoint}. Ensure Ollama is running."
        ) from exc

    with response:
        payload = response.read().decode("utf-8", errors="replace")
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
        if name:
            names.append(name)
    return list(dict.fromkeys(names))


def _ollama_available_models() -> list[str]:
    global _MODELS_CACHE
    if _MODELS_CACHE is not None:
        cached_at, names = _MODELS_CACHE
        if (time.time() - cached_at) <= _MODELS_CACHE_TTL_SECONDS:
            return names
    names = _fetch_ollama_models_uncached()
    _MODELS_CACHE = (time.time(), names)
    return names


def ollama_models() -> OllamaModelsResponse:
    warnings: list[str] = []
    try:
        models = _ollama_available_models()
    except ValueError as exc:
        models = []
        warnings.append(str(exc))

    env_model = str(os.getenv("COPYLOT_OLLAMA_MODEL", "")).strip()
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


def _detect_gpu_status_uncached() -> OllamaGpuStatusResponse:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider=None,
            deviceName=None,
            reason="No compatible CUDA GPU detected (nvidia-smi not found).",
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
        )
    if process.returncode != 0:
        stderr = str(process.stderr or "").strip()
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="cuda",
            deviceName=None,
            reason=stderr or "No eligible CUDA GPU reported by nvidia-smi.",
        )
    names = [line.strip() for line in str(process.stdout or "").splitlines() if line.strip()]
    if not names:
        return OllamaGpuStatusResponse(
            gpuEligible=False,
            gpuEnabledDefault=False,
            provider="cuda",
            deviceName=None,
            reason="No eligible CUDA GPU reported by nvidia-smi.",
        )
    return OllamaGpuStatusResponse(
        gpuEligible=True,
        gpuEnabledDefault=_env_bool("COPYLOT_OLLAMA_GPU_DEFAULT", True),
        provider="cuda",
        deviceName=names[0],
        reason=None,
    )


def ollama_gpu_status() -> OllamaGpuStatusResponse:
    global _GPU_STATUS_CACHE
    if _GPU_STATUS_CACHE is not None:
        cached_at, payload = _GPU_STATUS_CACHE
        if (time.time() - cached_at) <= _GPU_STATUS_CACHE_TTL_SECONDS:
            return payload
    payload = _detect_gpu_status_uncached()
    _GPU_STATUS_CACHE = (time.time(), payload)
    return payload


def _resolve_gpu_enabled(payload_gpu_enabled: bool | None) -> bool:
    status = ollama_gpu_status()
    if not status.gpuEligible:
        return False
    if payload_gpu_enabled is None:
        return bool(status.gpuEnabledDefault)
    return bool(payload_gpu_enabled)


def _build_messages(payload: OllamaChatRequest) -> tuple[str, list[dict[str, str]]]:
    user_message = str(payload.message).strip()
    if not user_message:
        raise ValueError("Chat message cannot be empty.")
    messages = [message.model_dump() for message in payload.messages if str(message.content).strip()]
    has_system = any(str(message.get("role", "")).strip().lower() == "system" for message in messages)
    if not has_system:
        messages.insert(0, {"role": "system", "content": _DEFAULT_SYSTEM_PROMPT})
    if not messages or messages[-1].get("role") != "user" or str(messages[-1].get("content", "")).strip() != user_message:
        messages.append({"role": "user", "content": user_message})
    return user_message, messages


def _open_ollama_request(
    payload: OllamaChatRequest,
    *,
    stream: bool,
    messages_override: list[dict[str, str]] | None = None,
):
    model = _resolve_model(payload.model)
    endpoint = _resolve_endpoint()
    if messages_override is None:
        _, messages = _build_messages(payload)
    else:
        messages = [
            {
                "role": str(item.get("role", "")).strip(),
                "content": str(item.get("content", "")),
            }
            for item in messages_override
            if str(item.get("role", "")).strip() and str(item.get("content", "")).strip()
        ]
        if not messages:
            raise ValueError("Chat request has no valid messages.")
    gpu_enabled = _resolve_gpu_enabled(payload.gpuEnabled)
    requested_num_gpu = _env_int("COPYLOT_OLLAMA_NUM_GPU", -1)
    num_gpu = requested_num_gpu if gpu_enabled else 0

    request_body = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": _env_float("COPYLOT_OLLAMA_TEMPERATURE", 0.2),
            "top_p": _env_float("COPYLOT_OLLAMA_TOP_P", 0.9),
            "num_predict": _env_int("COPYLOT_OLLAMA_NUM_PREDICT", _DEFAULT_NUM_PREDICT),
            "repeat_penalty": _env_float("COPYLOT_OLLAMA_REPEAT_PENALTY", 1.1),
            "num_gpu": num_gpu,
        },
    }
    request_bytes = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=request_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        response = urllib.request.urlopen(request, timeout=180)
        return model, response, messages
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        if detail:
            raise ValueError(f"Ollama request failed ({exc.code}): {detail}") from exc
        raise ValueError(f"Ollama request failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ValueError(
            f"Could not reach Ollama at {endpoint}. Ensure Ollama is running and model '{model}' is available."
        ) from exc


def ollama_chat(payload: OllamaChatRequest) -> OllamaChatResponse:
    model, response, messages = _open_ollama_request(payload, stream=False)

    def _read_non_stream(res) -> tuple[str, str, str]:
        with res:
            response_payload = res.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(response_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Ollama returned invalid JSON.") from exc
        message_obj = parsed.get("message") if isinstance(parsed, dict) else None
        if not isinstance(message_obj, dict):
            raise ValueError("Ollama response did not include a message.")
        chunk_content = _normalize_message_text(message_obj)
        chunk_role = str(message_obj.get("role", "assistant")).strip().lower()
        done_reason = str(parsed.get("done_reason", "")).strip().lower() if isinstance(parsed, dict) else ""
        return chunk_content, chunk_role, done_reason

    content, role, done_reason = _read_non_stream(response)
    if not content.strip():
        raise ValueError("Ollama response was empty.")
    if role not in {"assistant", "user", "system"}:
        role = "assistant"

    accumulated = content
    attempts = 0
    while done_reason == "length" and attempts < _MAX_CONTINUATION_ATTEMPTS:
        attempts += 1
        continuation_messages = [
            *messages,
            {"role": "assistant", "content": accumulated},
            {"role": "user", "content": _CONTINUATION_USER_PROMPT},
        ]
        _, continuation_response, _ = _open_ollama_request(
            payload,
            stream=False,
            messages_override=continuation_messages,
        )
        next_content, _, done_reason = _read_non_stream(continuation_response)
        if not next_content:
            break
        accumulated += next_content

    return OllamaChatResponse(
        model=model,
        message=ChatMessage(role=role, content=accumulated),
    )


def ollama_chat_stream(payload: OllamaChatRequest) -> tuple[str, Iterator[str]]:
    model, response, initial_messages = _open_ollama_request(payload, stream=True)

    def _iter_chunks() -> Iterator[str]:
        accumulated = ""
        current_response = response
        done_reason = ""
        attempts = 0

        while True:
            done_reason = ""
            with current_response:
                for raw_line in current_response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    message_obj = parsed.get("message") if isinstance(parsed, dict) else None
                    if isinstance(message_obj, dict):
                        content = _normalize_message_text(message_obj)
                        if content:
                            accumulated += content
                            yield content
                    if isinstance(parsed, dict) and parsed.get("done"):
                        done_reason = str(parsed.get("done_reason", "")).strip().lower()
                        break
            if done_reason != "length" or attempts >= _MAX_CONTINUATION_ATTEMPTS:
                break
            attempts += 1
            continuation_messages = [
                *initial_messages,
                {"role": "assistant", "content": accumulated},
                {"role": "user", "content": _CONTINUATION_USER_PROMPT},
            ]
            _, current_response, _ = _open_ollama_request(
                payload,
                stream=True,
                messages_override=continuation_messages,
            )

    return model, _iter_chunks()

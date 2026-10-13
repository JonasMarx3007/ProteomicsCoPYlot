import io
import json
import os
import urllib.error
from types import SimpleNamespace

import pytest

from app.services import chat_tools, provider_http


@pytest.mark.parametrize("action", ["install", "remove"])
@pytest.mark.parametrize("failure", ["overflow", "expired", "http", "invalid_name"])
def test_model_management_failure_never_reports_success_or_refreshes(monkeypatch, action, failure):
    monkeypatch.setenv("COPYLOT_PROVIDER_RESPONSE_MAX_BYTES", "16")
    calls = []

    def urlopen(request, **kwargs):
        calls.append(request)
        if failure == "http":
            raise urllib.error.HTTPError(request.full_url, 500, "private server detail", {}, None)
        return io.BytesIO(b"x" * 17)

    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", urlopen)
    monkeypatch.setattr(chat_tools, "_invalidate_models_cache", lambda *a: pytest.fail("Failed operation invalidated caches"))
    monkeypatch.setattr(chat_tools, "ollama_models", lambda **kw: pytest.fail("Failed operation reported success"))
    deadline = provider_http.provider_deadline.set(1 if failure == "expired" else None)
    try:
        with pytest.raises(ValueError) as error:
            getattr(chat_tools, f"ollama_{action}_model")("--insecure" if failure == "invalid_name" else "synthetic")
        assert "private server detail" not in str(error.value)
        assert len(calls) == (0 if failure in {"expired", "invalid_name"} else 1)
    finally:
        provider_http.provider_deadline.reset(deadline)


@pytest.mark.parametrize("cache_name,ttl_name", [
    ("_MODELS_CACHE", "_MODELS_CACHE_TTL_SECONDS"),
    ("_GPU_STATUS_CACHE", "_GPU_STATUS_CACHE_TTL_SECONDS"),
    ("_MODEL_CAPABILITY_CACHE", "_MODEL_CAPABILITY_CACHE_TTL_SECONDS"),
])
def test_provider_caches_are_bounded_and_sweep_expired_entries(monkeypatch, cache_name, ttl_name):
    cache = {}
    monkeypatch.setattr(chat_tools, cache_name, cache)
    monkeypatch.setattr(chat_tools, "_CACHE_MAX_ENTRIES", 3)
    clock = [100.0]
    monkeypatch.setattr(chat_tools.time, "monotonic", lambda: clock[0])
    ttl = getattr(chat_tools, ttl_name)
    _, generation = chat_tools._cache_get(cache, "missing", ttl)
    for key in ("a", "b", "c", "d"):
        chat_tools._cache_put(cache, key, key, generation)
    assert list(cache) == ["b", "c", "d"]
    chat_tools._cache_put(cache, "x" * 1025, "ignored", generation)
    assert len(cache) == 3
    assert chat_tools._cache_get(cache, "d", ttl)[0] == "d"
    clock[0] += ttl + 1
    assert chat_tools._cache_get(cache, "missing", ttl)[0] is None
    assert cache == {}


def test_capability_route_logic_limits_arbitrary_model_cache_keys(monkeypatch):
    monkeypatch.setattr(chat_tools, "_MODEL_CAPABILITY_CACHE", {})
    monkeypatch.setattr(chat_tools, "_CACHE_MAX_ENTRIES", 3)
    for index in range(10):
        chat_tools.model_capability("openai", f"synthetic-{index}")
    assert len(chat_tools._MODEL_CAPABILITY_CACHE) == 3
    model = chat_tools.model_capability("openai", "synthetic-9")
    assert chat_tools.model_capability("openai", "synthetic-9") is model


@pytest.mark.parametrize("explicit", [False, True])
def test_model_change_invalidates_endpoint_capabilities_and_inflight_cache_write(monkeypatch, explicit):
    base = "http://127.0.0.1:11435"
    monkeypatch.setenv("COPYLOT_OLLAMA_URL", base + "/api/chat")
    model_cache = {base: (0, ["old"]), "other": (0, ["keep"])}
    capabilities = {f"ollama|{base}|old": (0, "stale"), "openai||keep": (0, "keep")}
    monkeypatch.setattr(chat_tools, "_MODELS_CACHE", model_cache)
    monkeypatch.setattr(chat_tools, "_MODEL_CAPABILITY_CACHE", capabilities)
    generation = chat_tools._CACHE_GENERATION
    chat_tools._invalidate_models_cache(base if explicit else None)
    chat_tools._cache_put(model_cache, base, ["stale fetch finished late"], generation)
    assert model_cache == {"other": (0, ["keep"])}
    assert capabilities == {"openai||keep": (0, "keep")}


def test_concurrent_cache_writes_respect_capacity(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    cache = {}
    monkeypatch.setattr(chat_tools, "_CACHE_MAX_ENTRIES", 8)
    generation = chat_tools._CACHE_GENERATION
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: chat_tools._cache_put(cache, str(i), i, generation), range(100)))
    assert len(cache) == 8


@pytest.mark.parametrize("action,method,path", [("install", "POST", "pull"), ("remove", "DELETE", "delete")])
@pytest.mark.parametrize("configured", [False, True])
def test_default_management_and_refresh_use_chat_host(monkeypatch, action, method, path, configured):
    base = "http://127.0.0.1:11435" if configured else "http://127.0.0.1:11434"
    monkeypatch.delenv("COPYLOT_OLLAMA_URL", raising=False)
    if configured:
        monkeypatch.setenv("COPYLOT_OLLAMA_URL", f"{base}/api/chat")
    monkeypatch.setenv("OLLAMA_HOST", "http://unrelated.invalid:11434")
    monkeypatch.setattr(chat_tools, "_MODELS_CACHE", {base: (float("inf"), ["stale"])})
    calls = []

    def urlopen(request, **kwargs):
        calls.append((request.full_url, request.get_method()))
        if request.full_url.endswith("/api/tags"):
            return io.BytesIO(b'{"models": [{"name": "fresh"}]}')
        assert json.loads(request.data)["name"] == "synthetic-model"
        assert kwargs["timeout"] > 0
        return io.BytesIO(b'{}')

    monkeypatch.setattr(chat_tools.subprocess, "Popen", lambda *a, **kw: pytest.fail("Model management must not start a process"))
    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", urlopen)
    result = getattr(chat_tools, f"ollama_{action}_model")(" synthetic-model ")
    assert calls == [(f"{base}/api/{path}", method), (f"{base}/api/tags", "GET")]
    assert chat_tools._resolve_endpoint() == f"{base}/api/chat"
    assert os.environ["OLLAMA_HOST"] == "http://unrelated.invalid:11434"
    assert result.ok and result.models == ["fresh"]


@pytest.mark.parametrize('base,local', [
    ('http://127.0.0.1:11434', True), ('http://[::1]:11434', True),
    ('http://LOCALHOST.:11434', True), ('http://127.0.0.2:11434', True),
    ('http://localhost.synthetic.invalid:11434', False),
    ('http://127.0.0.1.synthetic.invalid:11434', False), ('https://remote.invalid', False),
])
@pytest.mark.parametrize('explicit_first', [False, True])
def test_gpu_policy_uses_resolved_host_not_override_or_call_order(monkeypatch, base, local, explicit_first):
    from app.schemas.chat import ChatRequest
    monkeypatch.setenv('COPYLOT_OLLAMA_URL', base + '/api/chat')
    monkeypatch.setattr(chat_tools, '_GPU_STATUS_CACHE', {})
    hardware_probes = []
    monkeypatch.setattr(chat_tools.shutil, 'which', lambda name: hardware_probes.append(name) or None)
    forms = [base + '/', None] if explicit_first else [None, base + '/']
    statuses = [chat_tools.ollama_gpu_status(value) for value in forms]
    assert statuses[0] == statuses[1]
    assert statuses[0].remoteEndpoint is not local
    assert len(chat_tools._GPU_STATUS_CACHE) == 1
    assert hardware_probes == (['nvidia-smi'] if local else [])
    requests = []
    monkeypatch.setattr(chat_tools, '_resolve_model', lambda *a: 'synthetic')
    monkeypatch.setattr(chat_tools, 'open_provider_request', lambda request, **kw: requests.append(request) or io.BytesIO())
    for value in forms:
        for enabled in (None, False, True):
            chat_tools._open_ollama_request(ChatRequest(message='test', ollamaUrl=value, gpuEnabled=enabled), messages=[{"role": "user", "content": "test"}])
    for request in requests:
        options = json.loads(request.data)['options']
        if local:
            assert options['num_gpu'] == 0
        else:
            assert 'num_gpu' not in options


@pytest.mark.parametrize('enabled,expected', [(None, 7), (True, 7), (False, 0)])
def test_local_gpu_preference_is_preserved(monkeypatch, enabled, expected):
    from app.schemas.chat import ChatRequest
    monkeypatch.setenv('COPYLOT_OLLAMA_URL', 'http://[::1]:11434')
    monkeypatch.setenv('COPYLOT_OLLAMA_GPU_DEFAULT', 'true')
    monkeypatch.setenv('COPYLOT_OLLAMA_NUM_GPU', '7')
    monkeypatch.setattr(chat_tools, '_GPU_STATUS_CACHE', {})
    monkeypatch.setattr(chat_tools.shutil, 'which', lambda _: 'synthetic-nvidia-smi')
    monkeypatch.setattr(chat_tools.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='Synthetic GPU', stderr=''))
    monkeypatch.setattr(chat_tools, '_resolve_model', lambda *a: 'synthetic')
    captured = []
    monkeypatch.setattr(chat_tools, 'open_provider_request', lambda request, **kw: captured.append(request) or io.BytesIO())
    chat_tools._open_ollama_request(ChatRequest(message='test', gpuEnabled=enabled), messages=[{"role":"user", "content":"test"}])
    assert json.loads(captured[0].data)['options']['num_gpu'] == expected


@pytest.mark.parametrize("action,method,path", [("install", "POST", "pull"), ("remove", "DELETE", "delete")])
@pytest.mark.parametrize("suffix", ["", "/api/chat"])
def test_http_management_method_destination_and_refresh(monkeypatch, action, method, path, suffix):
    base = "http://127.0.0.1:11436"
    monkeypatch.setenv("COPYLOT_OLLAMA_URL", "http://127.0.0.1:11435/api/chat")
    # A loopback endpoint on a port other than Ollama's must be allowed explicitly.
    monkeypatch.setenv("COPYLOT_OLLAMA_ALLOWED_ENDPOINTS", base)
    monkeypatch.setattr(chat_tools, "_MODELS_CACHE", {base: (float("inf"), ["stale"])})
    requests = []

    def urlopen(request, **kwargs):
        requests.append(request)
        if request.full_url.endswith("/api/tags"):
            return io.BytesIO(b'{"models": [{"name": "fresh"}]}')
        return io.BytesIO(b"")

    def no_cli(*args, **kwargs):
        pytest.fail("Explicit endpoints must not invoke the CLI")

    monkeypatch.setattr(provider_http.PROVIDER_OPENER, "open", urlopen)
    monkeypatch.setattr(chat_tools.subprocess, "run", no_cli)
    result = getattr(chat_tools, f"ollama_{action}_model")("synthetic-model", base + suffix)
    assert [(r.full_url, r.get_method()) for r in requests] == [
        (f"{base}/api/{path}", method), (f"{base}/api/tags", "GET")
    ]
    expected = {"name": "synthetic-model"}
    if action == "install":
        expected["stream"] = False
    assert json.loads(requests[0].data) == expected
    assert chat_tools._resolve_endpoint(base + suffix) == f"{base}/api/chat"
    assert result.ok and result.models == ["fresh"]

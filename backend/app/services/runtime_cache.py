from __future__ import annotations

import inspect
import sys
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_LOCK = RLock()
_CACHE_VERSION = 0
_CACHE: "OrderedDict[tuple[Any, ...], Any]" = OrderedDict()
_MAX_ENTRIES = 128
_MAX_ENTRY_BYTES = 12 * 1024 * 1024


def _freeze(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None), bytes)):
        return value
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze(inner_value)) for key, inner_value in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(item) for item in value))
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _freeze(value.model_dump())
    if hasattr(value, "dict") and callable(value.dict):
        return _freeze(value.dict())
    return repr(value)


def _estimate_size_bytes(value: Any) -> int:
    if isinstance(value, bytes):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="ignore"))
    memory_usage = getattr(value, "memory_usage", None)
    if callable(memory_usage):
        try:
            usage = memory_usage(deep=True)
            if hasattr(usage, "sum"):
                return int(usage.sum())
            return int(usage)
        except Exception:
            pass
    try:
        return int(sys.getsizeof(value))
    except Exception:
        return 0


def invalidate_runtime_cache(reason: str = "") -> int:
    del reason
    global _CACHE_VERSION
    with _LOCK:
        _CACHE_VERSION += 1
        _CACHE.clear()
        return _CACHE_VERSION


def runtime_cache_version() -> int:
    with _LOCK:
        return _CACHE_VERSION


def runtime_cache_info() -> dict[str, int]:
    with _LOCK:
        return {
            "version": _CACHE_VERSION,
            "entries": len(_CACHE),
            "maxEntries": _MAX_ENTRIES,
            "maxEntryBytes": _MAX_ENTRY_BYTES,
        }


def cached_call(
    namespace: str,
    key_data: Any,
    factory: Callable[[], T],
    *,
    copy_result: bool = False,
) -> T:
    version = runtime_cache_version()
    key = (namespace, version, _freeze(key_data))

    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return deepcopy(cached) if copy_result else cached

    result = factory()
    result_size = _estimate_size_bytes(result)
    if result_size > _MAX_ENTRY_BYTES:
        return result

    with _LOCK:
        if _CACHE_VERSION == version:
            _CACHE[key] = result
            _CACHE.move_to_end(key)
            while len(_CACHE) > _MAX_ENTRIES:
                _CACHE.popitem(last=False)

    return deepcopy(result) if copy_result else result


def cached_function(
    func: Callable[..., T],
    *,
    namespace: str | None = None,
    copy_result: bool = False,
) -> Callable[..., T]:
    if getattr(func, "_copylot_cached_wrapper", False):
        return func

    signature = inspect.signature(func)
    cache_namespace = namespace or f"{func.__module__}.{func.__name__}"

    def _compute_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        bound = signature.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)

    def _cache_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> T:
        key_data = _compute_key(args, kwargs)
        return cached_call(
            cache_namespace,
            key_data,
            lambda: func(*args, **kwargs),
            copy_result=copy_result,
        )

    if inspect.iscoroutinefunction(func):
        raise TypeError("cached_function currently supports synchronous callables only.")

    from functools import wraps

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        return _cache_call(args, kwargs)

    setattr(wrapper, "_copylot_cached_wrapper", True)
    return wrapper


def apply_cached_wrappers(
    namespace: dict[str, Any],
    names: list[str],
    *,
    copy_result: bool = False,
) -> None:
    for name in names:
        func = namespace.get(name)
        if not callable(func):
            continue
        namespace[name] = cached_function(
            func,
            namespace=f"{getattr(func, '__module__', 'app')}.{name}",
            copy_result=copy_result,
        )

from __future__ import annotations

import inspect
import logging
import sys
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from itertools import chain
from threading import RLock, get_ident
from typing import Any, Callable, TypeVar

import pandas as pd
from pydantic import BaseModel

from app.services.session_context import get_session_id
from app.services.plot_export import plot_output_format

T = TypeVar("T")

LOGGER = logging.getLogger(__name__)

_LOCK = RLock()
_CACHE_VERSION = 0
_GLOBAL_VERSION = 0
_SESSION_VERSIONS: dict[str, int] = {}
_CACHE: "OrderedDict[tuple[Any, ...], Any]" = OrderedDict()
_IN_FLIGHT: dict[tuple[Any, ...], tuple[int, Future[tuple[Any] | None]]] = {}
_MAX_ENTRIES = 128
_MAX_ENTRY_BYTES = 12 * 1024 * 1024


class UnfreezableArgument(TypeError):
    """Raised when a value cannot be turned into a lossless cache key."""


def _freeze(value: Any) -> Any:
    """Build a cache key fragment that distinguishes values exactly.

    Anything this cannot represent losslessly must raise rather than fall back
    to repr(). repr() truncates: a DataFrame differing only in the middle
    prints identically, so two different inputs would collide on one key and
    the second caller would silently receive the first caller's result. An
    unhashable argument is a reason to skip the cache, never to guess.
    """
    # `True == 1` and `1 == 1.0` in Python, and equal values hash equally, so a
    # bare bool or int in a key collides with the number beside it. The
    # `advanced` plot settings arrive as untyped JSON, where `{"x": true}` and
    # `{"x": 1}` are different instructions -- one renders as "True" and the
    # other as "1" -- and would otherwise share a cache entry. Tagging the type
    # keeps them apart.
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, (str, float, type(None), bytes)):
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
    raise UnfreezableArgument(
        f"{type(value).__name__} cannot be represented exactly in a cache key"
    )


_IMMUTABLE_TYPES = (str, bytes, int, float, bool, type(None), frozenset)


def _copy_for_caller(value: Any) -> Any:
    """Return a value the caller may safely mutate, as cheaply as correctness allows.

    A blanket deepcopy is not affordable here: on an 8000-feature volcano
    response it costs ~123 ms against ~130 ms to recompute, which would leave the
    cache saving about 5% of the work it exists to save. Most cached values do
    not need copying at all -- rendered plots are bytes and HTML is str, both
    immutable -- and DataFrames copy in well under a millisecond. Only the
    nested response models are genuinely expensive, and those pay the cost
    because a shared one can be corrupted for every later caller.
    """
    if isinstance(value, _IMMUTABLE_TYPES):
        return value
    if isinstance(value, tuple) and all(isinstance(item, _IMMUTABLE_TYPES) for item in value):
        return value
    copy_method = getattr(value, "copy", None)
    if callable(copy_method) and type(value).__module__.startswith("pandas"):
        return copy_method(deep=True)
    return deepcopy(value)


def _estimate_size_bytes(value: Any) -> int:
    """Estimate retained contents, stopping once the entry cap is exceeded.

    Count each visited object once, including dictionary keys and model fields.
    Pandas supplies its own deep estimate (shared buffers can be overcounted);
    this is a cache admission estimate, not an exact process-RAM measurement.
    Unknown payload types or failed sizing skip caching rather than count as zero.
    """
    seen: set[int] = set()
    pending = [iter((value,))]
    size = 0
    try:
        while pending:
            try:
                item = next(pending[-1])
            except StopIteration:
                pending.pop()
                continue
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, (pd.DataFrame, pd.Series)):
                usage = item.memory_usage(deep=True)
                size += int(usage.sum()) if isinstance(usage, pd.Series) else int(usage)
            else:
                size += sys.getsizeof(item)
                if isinstance(item, dict):
                    pending.append(chain(item.keys(), item.values()))
                elif isinstance(item, (list, tuple, set, frozenset)):
                    pending.append(iter(item))
                elif isinstance(item, BaseModel):
                    pending.append(iter((item.__dict__, item.__pydantic_extra__, item.__pydantic_private__)))
                elif not isinstance(item, (str, bytes, bytearray, int, float, complex, bool, type(None))):
                    return _MAX_ENTRY_BYTES + 1
            if size > _MAX_ENTRY_BYTES:
                return size
    except Exception:
        return _MAX_ENTRY_BYTES + 1
    return size


def invalidate_runtime_cache(reason: str = "", *, all_sessions: bool = False) -> int:
    """Invalidate this session's results; global resets must opt in explicitly."""
    del reason
    global _CACHE_VERSION, _GLOBAL_VERSION
    with _LOCK:
        _CACHE_VERSION += 1
        if all_sessions:
            _GLOBAL_VERSION = _CACHE_VERSION
            _SESSION_VERSIONS.clear()
            _CACHE.clear()
        else:
            session_id = get_session_id()
            _SESSION_VERSIONS[session_id] = _CACHE_VERSION
            for key in list(_CACHE):
                if key[2] == session_id:
                    del _CACHE[key]
        return _CACHE_VERSION


def runtime_cache_version() -> int:
    """Current session revision, also used to validate saved AI evidence."""
    with _LOCK:
        return _SESSION_VERSIONS.get(get_session_id(), _GLOBAL_VERSION)


def cached_call(
    namespace: str,
    key_data: Any,
    factory: Callable[[], T],
    *,
    copy_result: bool = True,
) -> T:
    """Return a cached result, computing it if absent.

    `copy_result` defaults to True: callers receive their own copy, so mutating
    a returned object cannot corrupt the entry for everyone who asks later.
    Pass False only for values that are never mutated downstream, and accept
    that the caller then shares the cached object.
    """
    session_id = get_session_id()
    try:
        frozen = _freeze(key_data)
    except UnfreezableArgument:
        # No exact key is possible, so a cache hit could serve the wrong result.
        # Recomputing is slower and correct; guessing is faster and wrong.
        LOGGER.debug("Skipping cache for %s: arguments cannot be keyed exactly", namespace)
        return factory()

    with _LOCK:
        version = _SESSION_VERSIONS.get(session_id, _GLOBAL_VERSION)
        key = (namespace, version, session_id, plot_output_format.get(), frozen)
        if key in _CACHE:
            cached = _CACHE[key]
            _CACHE.move_to_end(key)
            return _copy_for_caller(cached) if copy_result else cached
        pending = _IN_FLIGHT.get(key)
        owner = pending is None
        # Nested calculations must not wait on one another (including themselves).
        nested = any(thread == get_ident() for thread, _ in _IN_FLIGHT.values())
        if pending is None:
            future: Future[tuple[T] | None] = Future()
            _IN_FLIGHT[key] = (get_ident(), future)
        else:
            _, future = pending

    if not owner:
        if nested:
            return factory()
        shared = future.result()
        if runtime_cache_version() != version:
            return cached_call(namespace, key_data, factory, copy_result=copy_result)
        # Oversized/unknown objects retain the existing uncached behavior.
        if shared is None:
            return factory()
        return _copy_for_caller(shared[0]) if copy_result else shared[0]

    try:
        result = factory()
        cacheable = _estimate_size_bytes(result) <= _MAX_ENTRY_BYTES
        with _LOCK:
            if cacheable and _SESSION_VERSIONS.get(session_id, _GLOBAL_VERSION) == version:
                _CACHE[key] = result
                _CACHE.move_to_end(key)
                while len(_CACHE) > _MAX_ENTRIES:
                    _CACHE.popitem(last=False)
            future.set_result((result,) if cacheable else None)
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _LOCK:
            _IN_FLIGHT.pop(key, None)
    return _copy_for_caller(result) if cacheable and copy_result else result


def cached_function(
    func: Callable[..., T],
    *,
    namespace: str | None = None,
    copy_result: bool = True,
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
    copy_result: bool = True,
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

"""Reading COPYLOT_* settings from the environment, one way everywhere.

Eight modules each had their own copy of these. An unset or empty variable means
"use the default"; a value that does not parse also falls back to the default
rather than stopping the server.
"""
from __future__ import annotations

import os

TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def _raw(name: str) -> str:
    return str(os.getenv(name, "")).strip()


def env_flag(name: str, default: bool = False) -> bool:
    raw = _raw(name).lower()
    if not raw:
        return default
    return raw in TRUTHY_VALUES


def env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if minimum is None else max(minimum, value)


def env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = _raw(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if minimum is None else max(minimum, value)

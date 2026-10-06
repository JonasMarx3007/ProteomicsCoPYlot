"""Notebook memory budgets, scaled to physical/container RAM and configurable."""
import os

from app.services.upload_limits import _memory_capacity_bytes


def _configured_bytes(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw) * 1024**2
    except ValueError:
        raise ValueError(f"{name} must be a positive number of MiB.") from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive number of MiB.")
    return value


def notebook_memory_budgets():
    capacity = _memory_capacity_bytes()
    total = _configured_bytes('COPYLOT_NOTEBOOK_MEMORY_MB', capacity // 4 if capacity else 1024**3)
    session = _configured_bytes('COPYLOT_NOTEBOOK_SESSION_MEMORY_MB', total // 2)
    if session > total:
        raise ValueError('COPYLOT_NOTEBOOK_SESSION_MEMORY_MB cannot exceed COPYLOT_NOTEBOOK_MEMORY_MB.')
    return session, total

"""What a running assistant step is doing, for the chat's progress line.

A large local model thinks for a minute before its plan starts; the browser
polls this so the user sees "thinking, 640 tokens so far" instead of a still
spinner. Entries are keyed by a random id the browser chose for one step,
hold no content (only a phase and counts) and expire after ten minutes.
Each id is scoped to its analysis session.
"""
from __future__ import annotations

import threading
import time

from app.services.session_context import get_session_id

_ENTRIES: dict[tuple[str, str], dict] = {}
_LOCK = threading.Lock()
_TTL_SECONDS = 600


def _expire(now: float) -> None:
    for key in [key for key, entry in _ENTRIES.items() if now - entry["updated"] > _TTL_SECONDS]:
        _ENTRIES.pop(key, None)


def update(progress_id: str | None, phase: str, tokens: int = 0, calls: int | None = None) -> None:
    if not progress_id:
        return
    now = time.monotonic()
    with _LOCK:
        _expire(now)
        entry = _ENTRIES.setdefault((get_session_id(), progress_id), {"started": now, "calls": 0})
        entry.update(phase=phase, tokens=tokens, updated=now)
        if calls is not None:
            entry["calls"] = calls


def next_call(progress_id: str | None) -> None:
    """A new model call within the same step (a lookup round, the answer)."""
    if not progress_id:
        return
    with _LOCK:
        entry = _ENTRIES.get((get_session_id(), progress_id))
        if entry is not None:
            entry["calls"] = entry.get("calls", 0) + 1


def read(progress_id: str) -> dict:
    now = time.monotonic()
    with _LOCK:
        _expire(now)
        entry = _ENTRIES.get((get_session_id(), progress_id))
        if entry is None:
            return {"phase": "unknown", "tokens": 0, "seconds": 0, "calls": 0}
        return {"phase": entry.get("phase", "waiting"), "tokens": entry.get("tokens", 0),
                "seconds": round(now - entry["started"]), "calls": entry.get("calls", 0)}

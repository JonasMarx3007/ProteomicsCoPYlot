from __future__ import annotations

import time
from contextlib import contextmanager
from threading import RLock

from app.services.annotation_store import reset_all_annotations
from app.services.condition_palette_store import reset_condition_palettes
from app.services.phospho_localization import reset_localization_cutoff
from app.services.cloud_ai_consent import clear_cloud_ai_consent
from app.services.dataset_store import reset_all_datasets
from app.services.metadata_upload_store import reset_all_uploaded_metadata
from app.services.peptide_metadata_store import clear_peptide_metadata
from app.services.session_context import get_session_id, reset_session_id, rotate_session_id, set_session_id
from app.services.tool_access import clear_tool_session_auth
from app.services.viewer_portal import clear_viewer_session_auth
from app.services.env_settings import env_int

_LOCK = RLock()
_LAST_SEEN: dict[str, float] = {}
_DEFAULT_IDLE_SECONDS = 24 * 60 * 60
_DEFAULT_MAX_SESSIONS = 128
# A session that held data and was used this recently is never evicted to make
# room: neither for the session count nor for the memory budget. Only the idle
# timeout ends it.
_DEFAULT_PROTECT_SECONDS = 30 * 60
_BUDGET_CHECK_INTERVAL_SECONDS = 5.0
_LAST_BUDGET_CHECK = 0.0


def _frames_bytes(value, seen: set[int], depth: int = 0) -> int:
    """Bytes of the pandas frames held in a store entry (numeric buffers; cheap)."""
    import pandas as pd

    if depth > 6 or value is None or id(value) in seen:
        return 0
    seen.add(id(value))
    if isinstance(value, pd.DataFrame):
        return int(value.memory_usage(index=True, deep=False).sum())
    if isinstance(value, dict):
        return sum(_frames_bytes(item, seen, depth + 1) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_frames_bytes(item, seen, depth + 1) for item in value)
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, dict):
        return sum(_frames_bytes(item, seen, depth + 1) for item in fields.values())
    return 0


def session_data_bytes(session_id: str) -> int:
    """Memory one session's uploaded and derived matrices take."""
    from app.services import annotation_store, dataset_store, metadata_upload_store

    seen: set[int] = set()
    return sum(_frames_bytes(store.get(session_id), seen) for store in (
        dataset_store._DATASET_SESSIONS,
        annotation_store._ANNOTATIONS_BY_SESSION,
        metadata_upload_store._METADATA_SESSIONS,
    ))


def server_memory_budget_bytes() -> int:
    """Server-wide budget for session data: COPYLOT_SERVER_MEMORY_MB, else 60% of RAM.

    Deliberately generous: it only decides which idle sessions go first when the
    server fills up, and the session in use is never evicted for it.
    """
    from app.services.upload_limits import _memory_capacity_bytes

    configured = env_int("COPYLOT_SERVER_MEMORY_MB", 0, minimum=0)
    if configured:
        return configured * 1024**2
    capacity = _memory_capacity_bytes()
    return int(capacity * 0.6) if capacity else 8 * 1024**3


def _discard_session(session_id: str) -> None:
    token = set_session_id(session_id)
    try:
        clear_tool_session_auth()
        clear_cloud_ai_consent()
        clear_viewer_session_auth(reset_data=False)
        reset_all_annotations()
        reset_all_uploaded_metadata()
        reset_all_datasets()
        reset_condition_palettes()
        reset_localization_cutoff()
        clear_peptide_metadata()
        # Its data is gone, so the viewer must load the project again if the
        # same browser comes back (see viewer_bootstrap.bootstrap_current_viewer_session).
        from app.services.viewer_bootstrap import forget_viewer_session_bootstrap

        forget_viewer_session_bootstrap(session_id)
    finally:
        reset_session_id(token)


@contextmanager
def authenticated_session_rotation():
    previous = get_session_id()
    replacement = rotate_session_id()
    with _LOCK:
        _LAST_SEEN.pop(previous, None)
    _discard_session(previous)
    try:
        yield replacement
        touch_and_cleanup_sessions(replacement)
    except BaseException:
        with _LOCK:
            _LAST_SEEN.pop(replacement, None)
        _discard_session(replacement)
        raise


def expire_idle_session(session_id: str) -> bool:
    now = time.monotonic()
    idle_seconds = env_int("COPYLOT_SESSION_IDLE_SECONDS", _DEFAULT_IDLE_SECONDS, minimum=1)
    with _LOCK:
        last_seen = _LAST_SEEN.get(session_id)
        if last_seen is None or now - last_seen <= idle_seconds:
            return False
        _LAST_SEEN.pop(session_id, None)
    _discard_session(session_id)
    return True


def touch_and_cleanup_sessions(session_id: str) -> list[str]:
    """Record that a session was used, then end sessions that are idle or crowd the server.

    Overflow beyond COPYLOT_MAX_SESSIONS removes empty sessions first (a burst
    of cookieless requests creates nothing but those), then the least recently
    used sessions with data. A session with data used within
    COPYLOT_SESSION_PROTECT_SECONDS is never removed for room, and neither is
    the session making this request; the count may then exceed the maximum.
    """
    global _LAST_BUDGET_CHECK
    now = time.monotonic()
    idle_seconds = env_int("COPYLOT_SESSION_IDLE_SECONDS", _DEFAULT_IDLE_SECONDS, minimum=1)
    max_sessions = env_int("COPYLOT_MAX_SESSIONS", _DEFAULT_MAX_SESSIONS, minimum=1)
    protect_seconds = env_int("COPYLOT_SESSION_PROTECT_SECONDS", _DEFAULT_PROTECT_SECONDS, minimum=0)
    with _LOCK:
        _LAST_SEEN[session_id] = now
        expired = {
            existing
            for existing, last_seen in _LAST_SEEN.items()
            if existing != session_id and now - last_seen > idle_seconds
        }
        overflow = max(0, len(_LAST_SEEN) - len(expired) - max_sessions)
        if overflow:
            sizes = {existing: session_data_bytes(existing) for existing in _LAST_SEEN
                     if existing != session_id and existing not in expired}
            empty = sorted((last_seen, existing) for existing, last_seen in _LAST_SEEN.items()
                           if existing in sizes and sizes[existing] == 0)
            holding = sorted((last_seen, existing) for existing, last_seen in _LAST_SEEN.items()
                             if sizes.get(existing, 0) > 0 and now - last_seen > protect_seconds)
            expired.update(existing for _, existing in (empty + holding)[:overflow])
        if now - _LAST_BUDGET_CHECK >= _BUDGET_CHECK_INTERVAL_SECONDS:
            _LAST_BUDGET_CHECK = now
            budget = server_memory_budget_bytes()
            sizes = {existing: session_data_bytes(existing) for existing in _LAST_SEEN
                     if existing not in expired}
            total = sum(sizes.values())
            for last_seen, existing in sorted((last_seen, existing) for existing, last_seen in _LAST_SEEN.items()
                                              if existing in sizes):
                if total <= budget:
                    break
                if existing == session_id or now - last_seen <= protect_seconds or not sizes[existing]:
                    continue
                expired.add(existing)
                total -= sizes[existing]
        for existing in expired:
            _LAST_SEEN.pop(existing, None)

    for existing in sorted(expired):
        _discard_session(existing)
    return sorted(expired)

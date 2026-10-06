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
    now = time.monotonic()
    idle_seconds = env_int("COPYLOT_SESSION_IDLE_SECONDS", _DEFAULT_IDLE_SECONDS, minimum=1)
    max_sessions = env_int("COPYLOT_MAX_SESSIONS", _DEFAULT_MAX_SESSIONS, minimum=1)
    with _LOCK:
        _LAST_SEEN[session_id] = now
        expired = {
            existing
            for existing, last_seen in _LAST_SEEN.items()
            if existing != session_id and now - last_seen > idle_seconds
        }
        remaining = sorted(
            (
                (last_seen, existing)
                for existing, last_seen in _LAST_SEEN.items()
                if existing != session_id and existing not in expired
            ),
            key=lambda item: item[0],
        )
        overflow = max(0, len(_LAST_SEEN) - len(expired) - max_sessions)
        expired.update(existing for _, existing in remaining[:overflow])
        for existing in expired:
            _LAST_SEEN.pop(existing, None)

    for existing in sorted(expired):
        _discard_session(existing)
    return sorted(expired)

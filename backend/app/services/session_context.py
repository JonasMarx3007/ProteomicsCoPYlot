from __future__ import annotations

import os
import re
import uuid
from contextvars import ContextVar, Token

TRUTHY_VALUES = {"1", "true", "yes", "on"}

_SESSION_ID_CTX: ContextVar[str] = ContextVar("copylot_session_id", default="global")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _truthy_env(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in TRUTHY_VALUES


def session_isolation_enabled() -> bool:
    """Whether each browser session gets its own datasets, annotations and caches.

    Defaults on. With it off every request resolves to the session id "global", so
    two browsers on the same machine share one state: the second reads and can
    overwrite the first one's uploaded data. That is only ever safe for a
    single-user desktop run, so it has to be asked for rather than assumed.
    """
    return _truthy_env("COPYLOT_SESSION_ISOLATION", "1")


def session_cookie_name() -> str:
    value = str(os.getenv("COPYLOT_SESSION_COOKIE_NAME", "copylot_session_id")).strip()
    return value or "copylot_session_id"


def session_header_name() -> str:
    value = str(os.getenv("COPYLOT_SESSION_HEADER_NAME", "X-CoPYlot-Session")).strip()
    return value or "X-CoPYlot-Session"


def session_cookie_secure() -> bool:
    return _truthy_env("COPYLOT_SESSION_COOKIE_SECURE", "0")


def new_session_id() -> str:
    return uuid.uuid4().hex


def normalize_session_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return new_session_id()
    if _SESSION_ID_RE.fullmatch(text):
        return text
    return new_session_id()


def get_session_id() -> str:
    if not session_isolation_enabled():
        return "global"
    return _SESSION_ID_CTX.get()


def get_browser_session_id() -> str:
    """Return the request's browser ID even when dataset isolation is disabled."""
    return _SESSION_ID_CTX.get()


def rotate_session_id() -> str:
    """Replace the current session id with a fresh one and return it.

    Used on successful authentication. The id arrives from the client -- a cookie
    or a header -- so without rotation an attacker who plants a known id in the
    victim's browser and waits for them to log in can then replay it. Cookies are
    not origin-isolated, so any host under a shared parent domain can set one.
    """
    replacement = new_session_id()
    _SESSION_ID_CTX.set(replacement)
    return replacement


def set_session_id(session_id: str) -> Token[str]:
    return _SESSION_ID_CTX.set(normalize_session_id(session_id))


def reset_session_id(token: Token[str]) -> None:
    _SESSION_ID_CTX.reset(token)

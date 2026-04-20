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
    return _truthy_env("COPYLOT_SESSION_ISOLATION", "0")


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


def set_session_id(session_id: str) -> Token[str]:
    if not session_isolation_enabled():
        return _SESSION_ID_CTX.set("global")
    return _SESSION_ID_CTX.set(normalize_session_id(session_id))


def reset_session_id(token: Token[str]) -> None:
    _SESSION_ID_CTX.reset(token)

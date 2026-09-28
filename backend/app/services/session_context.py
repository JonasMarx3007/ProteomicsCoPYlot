from __future__ import annotations

import os
import re
import uuid
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps this module import-light
    from starlette.responses import Response

TRUTHY_VALUES = {"1", "true", "yes", "on"}

_SESSION_ID_CTX: ContextVar[str] = ContextVar("copylot_session_id", default="global")
_TAB_ID_CTX: ContextVar[str] = ContextVar("copylot_tab_id", default="")
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
    name = value or "copylot_session_id"
    tab = _TAB_ID_CTX.get()
    return f"{name}_{tab}" if tab else name


def session_cookie_path() -> str:
    tab = _TAB_ID_CTX.get()
    return f"/api/tabs/{tab}" if tab else "/"


class TabSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/tabs/'):
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse

        match = re.fullmatch(r'/api/tabs/([a-f0-9]{32})(/api/.*)', scope['path'])
        if match is None:
            return await JSONResponse({'detail': 'Invalid tab API path.'}, status_code=400)(scope, receive, send)
        if not session_isolation_enabled():
            return await JSONResponse({'detail': 'Independent tabs require session isolation.'}, status_code=503)(scope, receive, send)
        tab, path = match.groups()
        scoped = dict(scope, path=path, raw_path=path.encode('utf-8'))
        token = _TAB_ID_CTX.set(tab)
        try:
            await self.app(scoped, receive, send)
        finally:
            _TAB_ID_CTX.reset(token)


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


def set_session_cookie(response: "Response", session_id: str) -> None:
    """Hand the client the post-login session id.

    Authentication mints a new id and binds the grant to it, so the browser has
    to be told; otherwise it keeps sending the pre-login id and every later
    request reads as unauthenticated. Both login realms set the same cookie.
    """
    response.set_cookie(
        key=session_cookie_name(),
        value=session_id,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        path=session_cookie_path(),
    )


def set_session_id(session_id: str) -> Token[str]:
    return _SESSION_ID_CTX.set(normalize_session_id(session_id))


def reset_session_id(token: Token[str]) -> None:
    _SESSION_ID_CTX.reset(token)

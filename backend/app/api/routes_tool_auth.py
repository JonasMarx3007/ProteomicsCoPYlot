from __future__ import annotations

import logging

import os
import time
from collections import deque
from threading import RLock

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas.tool_auth import (
    ToolAuthLinkLoginRequest,
    ToolAuthLoginRequest,
    ToolAuthLoginResponse,
    ToolAuthLogoutResponse,
    ToolAuthStatusResponse,
)
from app.services.tool_access import (
    authenticate_tool_password,
    authenticate_tool_token,
    clear_tool_session_auth,
    tool_access_enabled,
    tool_session_authenticated,
)
from app.services.request_security import client_address

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/tool/auth", tags=["tool-auth"])
TRUTHY_VALUES = {"1", "true", "yes", "on"}
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_ATTEMPTS: dict[tuple[str, str], deque[float]] = {}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _rate_limit_enabled() -> bool:
    raw = str(os.getenv("COPYLOT_TOOL_LOGIN_RATE_LIMIT_ENABLED", "1")).strip().lower()
    return raw in TRUTHY_VALUES


def _client_key(request: Request) -> str:
    return client_address(request)


def _enforce_login_rate_limit(request: Request, *, bucket: str) -> None:
    if not _rate_limit_enabled():
        return
    limit = max(1, _env_int("COPYLOT_TOOL_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 12))
    window_seconds = max(1, _env_int("COPYLOT_TOOL_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300))
    now = time.monotonic()
    cutoff = now - window_seconds
    key = (_client_key(request), bucket)
    with _RATE_LIMIT_LOCK:
        stale_keys: list[tuple[str, str]] = []
        for existing_key, existing_attempts in _RATE_LIMIT_ATTEMPTS.items():
            while existing_attempts and existing_attempts[0] < cutoff:
                existing_attempts.popleft()
            if not existing_attempts:
                stale_keys.append(existing_key)
        for stale_key in stale_keys:
            _RATE_LIMIT_ATTEMPTS.pop(stale_key, None)
        attempts = _RATE_LIMIT_ATTEMPTS.setdefault(key, deque())
        if len(attempts) >= limit:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait and try again.")
        attempts.append(now)


@router.get("/status", response_model=ToolAuthStatusResponse)
def tool_auth_status_route() -> ToolAuthStatusResponse:
    enabled = tool_access_enabled()
    return ToolAuthStatusResponse(enabled=enabled, authenticated=tool_session_authenticated())


from app.services.session_context import (
    session_cookie_name,
    session_cookie_path,
    session_cookie_secure,
)


def _set_rotated_session_cookie(response: Response, session_id: str) -> None:
    """Hand the client the post-login session id.

    Authentication mints a new id and binds the grant to it, so the browser has to
    be told; otherwise it keeps sending the pre-login id and every later request
    reads as unauthenticated.
    """
    response.set_cookie(
        key=session_cookie_name(),
        value=session_id,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
        path=session_cookie_path(),
    )


@router.post("/login", response_model=ToolAuthLoginResponse)
def tool_auth_login_route(
    request: Request, payload: ToolAuthLoginRequest, response: Response
) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="password")
    try:
        rotated = authenticate_tool_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.exception("Tool access configuration is unavailable")
        raise HTTPException(
            status_code=500,
            detail="Tool access configuration is unavailable. Contact the administrator.",
        ) from exc
    _set_rotated_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True, sessionId=rotated)


@router.post("/link-login", response_model=ToolAuthLoginResponse)
def tool_auth_link_login_route(
    request: Request, payload: ToolAuthLinkLoginRequest, response: Response
) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="link")
    try:
        rotated = authenticate_tool_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.exception("Tool access configuration is unavailable")
        raise HTTPException(
            status_code=500,
            detail="Tool access configuration is unavailable. Contact the administrator.",
        ) from exc
    _set_rotated_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True, sessionId=rotated)


@router.post("/logout", response_model=ToolAuthLogoutResponse)
def tool_auth_logout_route() -> ToolAuthLogoutResponse:
    clear_tool_session_auth()
    return ToolAuthLogoutResponse(ok=True)

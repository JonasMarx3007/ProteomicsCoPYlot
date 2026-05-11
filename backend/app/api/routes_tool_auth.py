from __future__ import annotations

import os
import time
from collections import deque
from threading import RLock

from fastapi import APIRouter, HTTPException, Request

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
    forwarded = str(request.headers.get("x-forwarded-for", "")).split(",", 1)[0].strip()
    if forwarded:
        return forwarded
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_login_rate_limit(request: Request, *, bucket: str) -> None:
    if not _rate_limit_enabled():
        return
    limit = max(1, _env_int("COPYLOT_TOOL_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 12))
    window_seconds = max(1, _env_int("COPYLOT_TOOL_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300))
    now = time.monotonic()
    cutoff = now - window_seconds
    key = (_client_key(request), bucket)
    with _RATE_LIMIT_LOCK:
        attempts = _RATE_LIMIT_ATTEMPTS.setdefault(key, deque())
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait and try again.")
        attempts.append(now)


@router.get("/status", response_model=ToolAuthStatusResponse)
async def tool_auth_status_route() -> ToolAuthStatusResponse:
    enabled = tool_access_enabled()
    return ToolAuthStatusResponse(enabled=enabled, authenticated=tool_session_authenticated())


@router.post("/login", response_model=ToolAuthLoginResponse)
async def tool_auth_login_route(request: Request, payload: ToolAuthLoginRequest) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="password")
    try:
        authenticate_tool_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ToolAuthLoginResponse(ok=True)


@router.post("/link-login", response_model=ToolAuthLoginResponse)
async def tool_auth_link_login_route(request: Request, payload: ToolAuthLinkLoginRequest) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="link")
    try:
        authenticate_tool_token(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ToolAuthLoginResponse(ok=True)


@router.post("/logout", response_model=ToolAuthLogoutResponse)
async def tool_auth_logout_route() -> ToolAuthLogoutResponse:
    clear_tool_session_auth()
    return ToolAuthLogoutResponse(ok=True)

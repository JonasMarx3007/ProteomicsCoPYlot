from __future__ import annotations

import logging

import os
import time
from collections import deque
from threading import RLock

from fastapi import APIRouter, HTTPException, Request

from app.schemas.viewer_auth import (
    ViewerAuthLoginRequest,
    ViewerAuthLoginResponse,
    ViewerAuthLogoutResponse,
    ViewerAuthQrLoginRequest,
    ViewerAuthStatusResponse,
)
from app.services.viewer_portal import (
    authenticate_viewer_qr_session,
    authenticate_viewer_session,
    clear_viewer_session_auth,
    ensure_viewer_session_bootstrapped,
    viewer_portal_enabled,
    viewer_session_auth,
)
from app.services.request_security import client_address

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/viewer/auth", tags=["viewer-auth"])
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
    raw = str(os.getenv("COPYLOT_VIEWER_LOGIN_RATE_LIMIT_ENABLED", "1")).strip().lower()
    return raw in TRUTHY_VALUES


def _client_key(request: Request) -> str:
    return client_address(request)


def _enforce_login_rate_limit(request: Request, *, bucket: str) -> None:
    if not _rate_limit_enabled():
        return
    limit = max(1, _env_int("COPYLOT_VIEWER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 12))
    window_seconds = max(1, _env_int("COPYLOT_VIEWER_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 300))
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


@router.get("/status", response_model=ViewerAuthStatusResponse)
def viewer_auth_status_route() -> ViewerAuthStatusResponse:
    enabled = viewer_portal_enabled()
    if not enabled:
        return ViewerAuthStatusResponse(enabled=False, authenticated=False)

    current = viewer_session_auth()
    if current is None:
        return ViewerAuthStatusResponse(enabled=True, authenticated=False)

    try:
        refreshed = ensure_viewer_session_bootstrapped(force_reload=False)
    except FileNotFoundError as exc:
        clear_viewer_session_auth(reset_data=True)
        LOGGER.exception("Viewer access configuration is unavailable")
        raise HTTPException(
            status_code=500,
            detail="Viewer access configuration is unavailable. Contact the administrator.",
        ) from exc
    except Exception as exc:
        clear_viewer_session_auth(reset_data=True)
        LOGGER.exception("Failed to initialize viewer project session")
        raise HTTPException(status_code=500, detail="Failed to initialize viewer project session.") from exc

    return ViewerAuthStatusResponse(
        enabled=True,
        authenticated=True,
        project=refreshed.project,
        projectLabel=refreshed.project_label,
    )


@router.post("/login", response_model=ViewerAuthLoginResponse)
def viewer_auth_login_route(request: Request, payload: ViewerAuthLoginRequest) -> ViewerAuthLoginResponse:
    if not viewer_portal_enabled():
        raise HTTPException(status_code=404, detail="Viewer portal auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="password")

    try:
        auth = authenticate_viewer_session(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.exception("Viewer access configuration is unavailable")
        raise HTTPException(
            status_code=500,
            detail="Viewer access configuration is unavailable. Contact the administrator.",
        ) from exc
    except Exception as exc:
        LOGGER.exception("Failed to authenticate viewer session")
        raise HTTPException(status_code=500, detail="Failed to authenticate viewer session.") from exc

    return ViewerAuthLoginResponse(
        ok=True,
        project=auth.project,
        projectLabel=auth.project_label,
    )


@router.post("/qr-login", response_model=ViewerAuthLoginResponse)
def viewer_auth_qr_login_route(request: Request, payload: ViewerAuthQrLoginRequest) -> ViewerAuthLoginResponse:
    if not viewer_portal_enabled():
        raise HTTPException(status_code=404, detail="Viewer portal auth is not enabled.")
    _enforce_login_rate_limit(request, bucket="qr")

    try:
        auth = authenticate_viewer_qr_session(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        LOGGER.exception("Viewer access configuration is unavailable")
        raise HTTPException(
            status_code=500,
            detail="Viewer access configuration is unavailable. Contact the administrator.",
        ) from exc
    except Exception as exc:
        LOGGER.exception("Failed to authenticate viewer QR session")
        raise HTTPException(status_code=500, detail="Failed to authenticate viewer QR session.") from exc

    return ViewerAuthLoginResponse(
        ok=True,
        project=auth.project,
        projectLabel=auth.project_label,
    )


@router.post("/logout", response_model=ViewerAuthLogoutResponse)
def viewer_auth_logout_route() -> ViewerAuthLogoutResponse:
    clear_viewer_session_auth(reset_data=True)
    return ViewerAuthLogoutResponse(ok=True)

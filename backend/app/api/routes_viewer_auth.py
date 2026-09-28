from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas.viewer_auth import (
    ViewerAuthLoginRequest,
    ViewerAuthLoginResponse,
    ViewerAuthLogoutResponse,
    ViewerAuthQrLoginRequest,
    ViewerAuthStatusResponse,
)
from app.services.request_security import LoginRateLimit
from app.services.session_context import get_session_id, set_session_cookie
from app.services.viewer_portal import (
    authenticate_viewer_qr_session,
    authenticate_viewer_session,
    clear_viewer_session_auth,
    ensure_viewer_session_bootstrapped,
    viewer_portal_enabled,
    viewer_session_auth,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/viewer/auth", tags=["viewer-auth"])
LOGIN_RATE_LIMIT = LoginRateLimit("VIEWER")


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
def viewer_auth_login_route(
    request: Request, payload: ViewerAuthLoginRequest, response: Response
) -> ViewerAuthLoginResponse:
    if not viewer_portal_enabled():
        raise HTTPException(status_code=404, detail="Viewer portal auth is not enabled.")
    LOGIN_RATE_LIMIT.enforce(request, bucket="password")

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

    LOGIN_RATE_LIMIT.clear(request, bucket="password")
    set_session_cookie(response, get_session_id())
    return ViewerAuthLoginResponse(
        ok=True,
        project=auth.project,
        projectLabel=auth.project_label,
    )


@router.post("/qr-login", response_model=ViewerAuthLoginResponse)
def viewer_auth_qr_login_route(
    request: Request, payload: ViewerAuthQrLoginRequest, response: Response
) -> ViewerAuthLoginResponse:
    if not viewer_portal_enabled():
        raise HTTPException(status_code=404, detail="Viewer portal auth is not enabled.")
    LOGIN_RATE_LIMIT.enforce(request, bucket="qr")

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

    LOGIN_RATE_LIMIT.clear(request, bucket="qr")
    set_session_cookie(response, get_session_id())
    return ViewerAuthLoginResponse(
        ok=True,
        project=auth.project,
        projectLabel=auth.project_label,
    )


@router.post("/logout", response_model=ViewerAuthLogoutResponse)
def viewer_auth_logout_route() -> ViewerAuthLogoutResponse:
    clear_viewer_session_auth(reset_data=True)
    return ViewerAuthLogoutResponse(ok=True)

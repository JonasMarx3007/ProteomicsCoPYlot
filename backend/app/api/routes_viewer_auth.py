from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.viewer_auth import (
    ViewerAuthLoginRequest,
    ViewerAuthLoginResponse,
    ViewerAuthLogoutResponse,
    ViewerAuthStatusResponse,
)
from app.services.viewer_portal import (
    authenticate_viewer_session,
    clear_viewer_session_auth,
    ensure_viewer_session_bootstrapped,
    viewer_portal_enabled,
    viewer_session_auth,
)

router = APIRouter(prefix="/api/viewer/auth", tags=["viewer-auth"])


@router.get("/status", response_model=ViewerAuthStatusResponse)
async def viewer_auth_status_route() -> ViewerAuthStatusResponse:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        clear_viewer_session_auth(reset_data=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize viewer project session: {exc}",
        ) from exc

    return ViewerAuthStatusResponse(
        enabled=True,
        authenticated=True,
        project=refreshed.project,
        projectLabel=refreshed.project_label,
    )


@router.post("/login", response_model=ViewerAuthLoginResponse)
async def viewer_auth_login_route(payload: ViewerAuthLoginRequest) -> ViewerAuthLoginResponse:
    if not viewer_portal_enabled():
        raise HTTPException(status_code=404, detail="Viewer portal auth is not enabled.")

    try:
        auth = authenticate_viewer_session(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to authenticate viewer session: {exc}",
        ) from exc

    return ViewerAuthLoginResponse(
        ok=True,
        project=auth.project,
        projectLabel=auth.project_label,
    )


@router.post("/logout", response_model=ViewerAuthLogoutResponse)
async def viewer_auth_logout_route() -> ViewerAuthLogoutResponse:
    clear_viewer_session_auth(reset_data=True)
    return ViewerAuthLogoutResponse(ok=True)


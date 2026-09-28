from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas.tool_auth import (
    ToolAuthLinkLoginRequest,
    ToolAuthLoginRequest,
    ToolAuthLoginResponse,
    ToolAuthLogoutResponse,
    ToolAuthStatusResponse,
)
from app.services.request_security import LoginRateLimit
from app.services.session_context import set_session_cookie
from app.services.tool_access import (
    authenticate_tool_password,
    authenticate_tool_token,
    clear_tool_session_auth,
    tool_access_enabled,
    tool_session_authenticated,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/tool/auth", tags=["tool-auth"])
LOGIN_RATE_LIMIT = LoginRateLimit("TOOL")


@router.get("/status", response_model=ToolAuthStatusResponse)
def tool_auth_status_route() -> ToolAuthStatusResponse:
    enabled = tool_access_enabled()
    return ToolAuthStatusResponse(enabled=enabled, authenticated=tool_session_authenticated())


@router.post("/login", response_model=ToolAuthLoginResponse)
def tool_auth_login_route(
    request: Request, payload: ToolAuthLoginRequest, response: Response
) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    LOGIN_RATE_LIMIT.enforce(request, bucket="password")
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
    LOGIN_RATE_LIMIT.clear(request, bucket="password")
    set_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True)


@router.post("/link-login", response_model=ToolAuthLoginResponse)
def tool_auth_link_login_route(
    request: Request, payload: ToolAuthLinkLoginRequest, response: Response
) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    LOGIN_RATE_LIMIT.enforce(request, bucket="link")
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
    LOGIN_RATE_LIMIT.clear(request, bucket="link")
    set_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True)


@router.post("/logout", response_model=ToolAuthLogoutResponse)
def tool_auth_logout_route() -> ToolAuthLogoutResponse:
    clear_tool_session_auth()
    return ToolAuthLogoutResponse(ok=True)

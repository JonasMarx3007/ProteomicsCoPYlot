from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas.tool_auth import (
    ToolAuthLinkLoginRequest,
    ToolAuthLoginRequest,
    ToolAuthLoginResponse,
    ToolAuthLogoutResponse,
    ToolAuthStatusResponse,
)
from app.api.login_attempt import login_attempt
from app.services.request_security import LoginRateLimit
from app.services.session_context import set_session_cookie
from app.services.tool_access import (
    authenticate_tool_password,
    authenticate_tool_token,
    clear_tool_session_auth,
    tool_access_enabled,
    tool_session_authenticated,
)

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
    rotated = login_attempt(
        request,
        LOGIN_RATE_LIMIT,
        bucket="password",
        access="Tool",
        failure="Failed to authenticate tool session",
        authenticate=lambda: authenticate_tool_password(payload.password),
    )
    set_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True)


@router.post("/link-login", response_model=ToolAuthLoginResponse)
def tool_auth_link_login_route(
    request: Request, payload: ToolAuthLinkLoginRequest, response: Response
) -> ToolAuthLoginResponse:
    if not tool_access_enabled():
        raise HTTPException(status_code=404, detail="Tool access auth is not enabled.")
    rotated = login_attempt(
        request,
        LOGIN_RATE_LIMIT,
        bucket="link",
        access="Tool",
        failure="Failed to authenticate tool session",
        authenticate=lambda: authenticate_tool_token(payload.token),
    )
    set_session_cookie(response, rotated)
    return ToolAuthLoginResponse(ok=True)


@router.post("/logout", response_model=ToolAuthLogoutResponse)
def tool_auth_logout_route() -> ToolAuthLogoutResponse:
    clear_tool_session_auth()
    return ToolAuthLogoutResponse(ok=True)

from __future__ import annotations

from pydantic import BaseModel, Field


class ViewerAuthStatusResponse(BaseModel):
    enabled: bool
    authenticated: bool
    project: str | None = None
    projectLabel: str | None = None


class ViewerAuthLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096)


class ViewerAuthQrLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class ViewerAuthLoginResponse(BaseModel):
    ok: bool
    project: str
    projectLabel: str
    # Authentication rotates the session id, so a client that identifies itself with
    # the X-CoPYlot-Session header rather than a cookie needs to be told the new
    # one; otherwise it keeps sending the pre-login id and reads as anonymous.
    sessionId: str = ""


class ViewerAuthLogoutResponse(BaseModel):
    ok: bool

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolAuthStatusResponse(BaseModel):
    enabled: bool
    authenticated: bool


class ToolAuthLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096)


class ToolAuthLinkLoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=4096)


class ToolAuthLoginResponse(BaseModel):
    ok: bool
    # Authentication rotates the session id, so a client that identifies itself with
    # the X-CoPYlot-Session header rather than a cookie needs to be told the new
    # one; otherwise it keeps sending the pre-login id and reads as anonymous.
    sessionId: str = ""


class ToolAuthLogoutResponse(BaseModel):
    ok: bool

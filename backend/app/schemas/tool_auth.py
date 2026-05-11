from __future__ import annotations

from pydantic import BaseModel


class ToolAuthStatusResponse(BaseModel):
    enabled: bool
    authenticated: bool


class ToolAuthLoginRequest(BaseModel):
    password: str


class ToolAuthLinkLoginRequest(BaseModel):
    token: str


class ToolAuthLoginResponse(BaseModel):
    ok: bool


class ToolAuthLogoutResponse(BaseModel):
    ok: bool

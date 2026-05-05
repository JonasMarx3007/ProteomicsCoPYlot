from __future__ import annotations

from pydantic import BaseModel


class ViewerAuthStatusResponse(BaseModel):
    enabled: bool
    authenticated: bool
    project: str | None = None
    projectLabel: str | None = None


class ViewerAuthLoginRequest(BaseModel):
    password: str


class ViewerAuthQrLoginRequest(BaseModel):
    token: str


class ViewerAuthLoginResponse(BaseModel):
    ok: bool
    project: str
    projectLabel: str


class ViewerAuthLogoutResponse(BaseModel):
    ok: bool

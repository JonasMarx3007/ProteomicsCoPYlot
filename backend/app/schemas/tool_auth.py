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


class ToolAuthLogoutResponse(BaseModel):
    ok: bool

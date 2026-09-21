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
    # The rotated session id is deliberately NOT in this body. It is set as an
    # HttpOnly cookie and, for a client that identifies itself with the
    # X-CoPYlot-Session header instead, it is readable from the `Set-Cookie`
    # response header -- which is where a non-browser client reads it anyway.
    # Putting it in the body as well handed a live authenticated session to
    # anything that can read a response: an injected script, a logger, a proxy.


class ToolAuthLogoutResponse(BaseModel):
    ok: bool

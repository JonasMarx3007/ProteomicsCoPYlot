from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RRuntimeStatusResponse(BaseModel):
    available: bool
    executable: str | None = None
    version: str | None = None
    versionOutput: str | None = None
    detectedFrom: Literal["env", "path", "common_path"] | None = None
    candidates: list[str] = Field(default_factory=list)
    error: str | None = None

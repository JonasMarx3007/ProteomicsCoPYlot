from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field

ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(default="", min_length=0)


class OllamaChatRequest(BaseModel):
    message: str = Field(default="", min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)
    model: str | None = Field(default=None, min_length=1)
    gpuEnabled: bool | None = None


class OllamaChatResponse(BaseModel):
    model: str
    message: ChatMessage


class OllamaGpuStatusResponse(BaseModel):
    gpuEligible: bool
    gpuEnabledDefault: bool
    provider: str | None = None
    deviceName: str | None = None
    reason: str | None = None


class OllamaModelsResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    selectedModel: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModuleContextRequest(BaseModel):
    moduleKey: str = Field(default="", min_length=1)


class ModuleContextResponse(BaseModel):
    moduleKey: str
    moduleTitle: str
    manualTitle: str | None = None
    manualPath: str | None = None
    contextPrompt: str
    contextSummary: str
    contextData: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

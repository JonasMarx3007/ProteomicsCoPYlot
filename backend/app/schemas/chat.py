from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field

ChatRole = Literal["system", "user", "assistant"]
ChatProvider = Literal["ollama", "openai", "anthropic", "gemini"]
ModelContextTier = Literal["compact", "standard", "extended"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(default="", min_length=0)


class OllamaChatRequest(BaseModel):
    message: str = Field(default="", min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)
    provider: ChatProvider = "ollama"
    model: str | None = Field(default=None, min_length=1)
    gpuEnabled: bool | None = None
    apiKey: str | None = Field(default=None, min_length=1)
    temperature: float | None = None
    maxTokens: int | None = None
    ollamaUrl: str | None = Field(default=None, min_length=1)


class OllamaChatResponse(BaseModel):
    model: str
    message: ChatMessage


class OllamaGpuStatusResponse(BaseModel):
    gpuEligible: bool
    gpuEnabledDefault: bool
    provider: str | None = None
    deviceName: str | None = None
    reason: str | None = None
    remoteEndpoint: bool = False
    acceleration: Literal["gpu", "cpu", "unknown"] = "unknown"


class OllamaModelsResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    selectedModel: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelCapabilityResponse(BaseModel):
    provider: ChatProvider
    model: str
    level: Literal[1, 2, 3]
    label: Literal["Low", "Medium", "High"]
    contextTier: ModelContextTier
    contextWindow: int | None = None
    parameterCountB: float | None = None
    supportsTools: bool | None = None
    supportsVision: bool | None = None
    source: Literal["metadata", "model_name", "configured", "fallback"] = "fallback"
    reason: str


class OllamaModelManageRequest(BaseModel):
    model: str = Field(default="", min_length=1)
    endpoint: str | None = Field(default=None, min_length=1)


class OllamaModelManageResponse(BaseModel):
    ok: bool
    action: Literal["install", "remove"]
    model: str
    detail: str
    models: list[str] = Field(default_factory=list)
    selectedModel: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModuleContextRequest(BaseModel):
    moduleKey: str = Field(default="", min_length=1)
    workflow: str | None = Field(default=None, min_length=1)
    mode: str | None = Field(default=None, min_length=1)
    contextTier: ModelContextTier | None = None


class ModuleContextResponse(BaseModel):
    moduleKey: str
    moduleTitle: str
    manualTitle: str | None = None
    manualPath: str | None = None
    contextPrompt: str
    contextSummary: str
    contextTier: ModelContextTier = "compact"
    contextData: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

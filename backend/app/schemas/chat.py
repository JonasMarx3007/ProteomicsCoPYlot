from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChatRole = Literal["system", "user", "assistant"]
ChatProvider = Literal["ollama", "openai", "anthropic", "gemini"]
ModelContextTier = Literal["compact", "standard", "extended"]
_CHAT_MESSAGE_MAX_CHARS = 32_000
_CHAT_HISTORY_MESSAGE_MAX_CHARS = 256_000
_CHAT_HISTORY_MAX_MESSAGES = 64
_CHAT_REQUEST_MAX_CHARS = 1_000_000


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(default="", min_length=0, max_length=_CHAT_HISTORY_MESSAGE_MAX_CHARS)


class OllamaChatRequest(BaseModel):
    message: str = Field(default="", min_length=1, max_length=_CHAT_MESSAGE_MAX_CHARS)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=_CHAT_HISTORY_MAX_MESSAGES)
    provider: ChatProvider = "ollama"
    model: str | None = Field(default=None, min_length=1, max_length=512)
    gpuEnabled: bool | None = None
    apiKey: str | None = Field(default=None, min_length=1, max_length=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    maxTokens: int | None = Field(default=None, ge=1, le=131_072)
    ollamaUrl: str | None = Field(default=None, min_length=1, max_length=2048)
    analysisContext: str | None = Field(default=None, max_length=128_000)

    @model_validator(mode="after")
    def validate_total_text_size(self) -> "OllamaChatRequest":
        total_chars = (
            len(self.message)
            + sum(len(item.content) for item in self.messages)
            + len(self.analysisContext or "")
        )
        if total_chars > _CHAT_REQUEST_MAX_CHARS:
            raise ValueError("Chat request exceeds the total text limit.")
        return self


class CloudAiConsentVersionRequest(BaseModel):
    disclosureVersion: str = Field(default="", min_length=1, max_length=64)


class CloudAiConsentStatusResponse(BaseModel):
    provider: ChatProvider
    providerLabel: str
    required: bool
    granted: bool
    disclosureVersion: str
    transmitted: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    notice: str


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
    model: str = Field(default="", min_length=1, max_length=512)
    endpoint: str | None = Field(default=None, min_length=1, max_length=2048)


class OllamaModelManageResponse(BaseModel):
    ok: bool
    action: Literal["install", "remove"]
    model: str
    detail: str
    models: list[str] = Field(default_factory=list)
    selectedModel: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModuleContextRequest(BaseModel):
    moduleKey: str = Field(default="", min_length=1, max_length=512)
    workflow: str | None = Field(default=None, min_length=1, max_length=4096)
    mode: str | None = Field(default=None, min_length=1, max_length=16_384)
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

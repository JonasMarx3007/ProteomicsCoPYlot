from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ChatRole = Literal["system", "user", "assistant"]
ChatProvider = Literal["ollama", "openai_compatible", "openai", "anthropic", "gemini"]
ModelContextTier = Literal["compact", "standard", "extended"]
_CHAT_MESSAGE_MAX_CHARS = 32_000
_CHAT_HISTORY_MESSAGE_MAX_CHARS = 256_000
_CHAT_HISTORY_MAX_MESSAGES = 64
_CHAT_REQUEST_MAX_CHARS = 1_000_000


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(default="", min_length=0, max_length=_CHAT_HISTORY_MESSAGE_MAX_CHARS)


class ChatRequest(BaseModel):
    message: str = Field(default="", min_length=1, max_length=_CHAT_MESSAGE_MAX_CHARS)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=_CHAT_HISTORY_MAX_MESSAGES)
    provider: ChatProvider = "ollama"
    model: str | None = Field(default=None, min_length=1, max_length=512)
    gpuEnabled: bool | None = None
    apiKey: str | None = Field(default=None, min_length=1, max_length=8192)
    ollamaUrl: str | None = Field(default=None, min_length=1, max_length=2048)
    # A local server speaking the OpenAI-compatible API, e.g. http://host:8080/v1.
    localServerUrl: str | None = Field(default=None, min_length=1, max_length=2048)
    # The user's choice of assistant level; "auto" uses the model's classification.
    assistantLevel: Literal["auto", "basic", "standard", "advanced"] = "auto"

    @model_validator(mode="after")
    def validate_total_text_size(self) -> "ChatRequest":
        total_chars = (
            len(self.message)
            + sum(len(item.content) for item in self.messages)
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


class OllamaGpuStatusResponse(BaseModel):
    gpuEligible: bool
    gpuEnabledDefault: bool
    provider: str | None = None
    deviceName: str | None = None
    reason: str | None = None
    remoteEndpoint: bool = False
    acceleration: Literal["gpu", "cpu", "unknown"] = "unknown"


class LocalServerModelsRequest(BaseModel):
    endpoint: str | None = Field(default=None, min_length=1, max_length=2048)
    apiKey: str | None = Field(default=None, min_length=1, max_length=8192)


class OllamaModelsResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    selectedModel: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelCapabilityResponse(BaseModel):
    assessment: Literal["tested", "observed", "configured", "inferred", "unknown"] = "unknown"
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
    # The assistant level this model gets automatically (Basic/Standard/Advanced).
    levelName: Literal["Basic", "Standard", "Advanced"] = "Basic"
    # Thinks before answering; its thinking counts against the reply budget.
    reasoning: bool = False
    # Reply budget the assistant grants this model, thinking included.
    outputTokens: int = 1024


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


class AiOperatorPolicyResponse(BaseModel):
    providers: list[str]
    models: dict[str, list[str]]
    modelManagement: bool


class ProviderDefaultsResponse(BaseModel):
    models: dict[str, str]
    policy: AiOperatorPolicyResponse
    # The operator's preset local OpenAI-compatible server (COPYLOT_LOCAL_AI_URL), or "".
    localServerUrl: str = ""

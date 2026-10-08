from __future__ import annotations

from threading import RLock

from app.schemas.chat import ChatProvider, CloudAiConsentStatusResponse
from app.services.session_context import get_browser_session_id

CLOUD_AI_DISCLOSURE_VERSION = "2"
CLOUD_PROVIDERS: tuple[ChatProvider, ...] = ("openai", "anthropic", "gemini")

_PROVIDER_LABELS: dict[ChatProvider, str] = {
    "ollama": "Ollama",
    "openai_compatible": "Local server (OpenAI-compatible)",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
}
_TRANSMITTED = (
    "Your prompt and the visible conversation history",
    "Generated page/project context, including dataset names and dimensions",
    "Relevant protein or site identifiers, sample/condition labels, and calculated summaries",
    "Available tabs and plot controls, their selected values, and receipts for requested view changes",
)
_EXCLUDED = (
    "Uploaded files and full raw or processed abundance matrices",
    "Local filesystem paths and unrelated datasets",
    "The API key field as prompt or experimental context (the key is used only in the provider authentication header)",
)
_NOTICE = (
    "This request sends the listed experimental context from Proteomics CoPYlot to {provider}. "
    "That provider processes it under its own data terms. Consent applies only to this provider "
    "and this app session, and can be revoked in AI Settings. The default Ollama endpoint is the local alternative; "
    "a custom Ollama endpoint sends context to that configured host."
)

_LOCK = RLock()
_GRANTS_BY_SESSION: dict[str, dict[ChatProvider, str]] = {}
_MAX_CONSENT_SESSIONS = 512


class CloudAiConsentRequired(ValueError):
    def __init__(self, provider: ChatProvider) -> None:
        self.provider = provider
        super().__init__(
            f"Cloud AI consent is required before sending analysis context to {_PROVIDER_LABELS[provider]}."
        )

    def detail(self) -> dict[str, object]:
        status = cloud_ai_consent_status(self.provider)
        return {
            "code": "cloud_ai_consent_required",
            **status.model_dump(),
        }


def _normalized_provider(provider: str) -> ChatProvider:
    value = str(provider or "").strip().lower()
    if value not in _PROVIDER_LABELS:
        raise ValueError(f"Unsupported chat provider '{provider}'.")
    return value  # type: ignore[return-value]


def cloud_ai_consent_status(provider: str) -> CloudAiConsentStatusResponse:
    normalized = _normalized_provider(provider)
    required = normalized in CLOUD_PROVIDERS
    granted = not required
    if required:
        with _LOCK:
            granted = (
                _GRANTS_BY_SESSION.get(get_browser_session_id(), {}).get(normalized)
                == CLOUD_AI_DISCLOSURE_VERSION
            )
    label = _PROVIDER_LABELS[normalized]
    return CloudAiConsentStatusResponse(
        provider=normalized,
        providerLabel=label,
        required=required,
        granted=granted,
        disclosureVersion=CLOUD_AI_DISCLOSURE_VERSION,
        transmitted=list(_TRANSMITTED),
        excluded=list(_EXCLUDED),
        notice=_NOTICE.format(provider=label),
    )


def grant_cloud_ai_consent(provider: str, disclosure_version: str) -> CloudAiConsentStatusResponse:
    normalized = _normalized_provider(provider)
    if normalized not in CLOUD_PROVIDERS:
        return cloud_ai_consent_status(normalized)
    if str(disclosure_version or "").strip() != CLOUD_AI_DISCLOSURE_VERSION:
        raise ValueError("The cloud AI disclosure changed. Review the current notice before confirming.")
    with _LOCK:
        session_id = get_browser_session_id()
        if session_id not in _GRANTS_BY_SESSION and len(_GRANTS_BY_SESSION) >= _MAX_CONSENT_SESSIONS:
            _GRANTS_BY_SESSION.pop(next(iter(_GRANTS_BY_SESSION)))
        grants = _GRANTS_BY_SESSION.setdefault(session_id, {})
        grants[normalized] = CLOUD_AI_DISCLOSURE_VERSION
    return cloud_ai_consent_status(normalized)


def revoke_cloud_ai_consent(provider: str) -> CloudAiConsentStatusResponse:
    normalized = _normalized_provider(provider)
    with _LOCK:
        session_id = get_browser_session_id()
        grants = _GRANTS_BY_SESSION.get(session_id)
        if grants is not None:
            grants.pop(normalized, None)
            if not grants:
                _GRANTS_BY_SESSION.pop(session_id, None)
    return cloud_ai_consent_status(normalized)


def require_cloud_ai_consent(provider: ChatProvider) -> None:
    if provider in CLOUD_PROVIDERS and not cloud_ai_consent_status(provider).granted:
        raise CloudAiConsentRequired(provider)


def clear_cloud_ai_consent() -> None:
    with _LOCK:
        _GRANTS_BY_SESSION.pop(get_browser_session_id(), None)

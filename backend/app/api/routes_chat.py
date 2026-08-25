from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.schemas.chat import (
    ChatProvider,
    CloudAiConsentStatusResponse,
    CloudAiConsentVersionRequest,
    ModelCapabilityResponse,
    ModuleContextRequest,
    ModuleContextResponse,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaGpuStatusResponse,
    OllamaModelManageRequest,
    OllamaModelManageResponse,
    OllamaModelsResponse,
)
from app.services.ai_context_tools import build_module_context
from app.services.chat_tools import (
    ai_mode_enabled,
    chat_stream,
    model_capability,
    ollama_chat,
    ollama_chat_stream,
    ollama_gpu_status,
    ollama_install_model,
    ollama_models,
    ollama_remove_model,
)
from app.services.cloud_ai_consent import (
    CloudAiConsentRequired,
    cloud_ai_consent_status,
    grant_cloud_ai_consent,
    revoke_cloud_ai_consent,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/cloud-consent/{provider}", response_model=CloudAiConsentStatusResponse)
def cloud_ai_consent_status_route(provider: ChatProvider) -> CloudAiConsentStatusResponse:
    return cloud_ai_consent_status(provider)


@router.post("/cloud-consent/{provider}/grant", response_model=CloudAiConsentStatusResponse)
def cloud_ai_consent_grant_route(
    provider: ChatProvider,
    payload: CloudAiConsentVersionRequest,
) -> CloudAiConsentStatusResponse:
    try:
        return grant_cloud_ai_consent(provider, payload.disclosureVersion)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/cloud-consent/{provider}/revoke", response_model=CloudAiConsentStatusResponse)
def cloud_ai_consent_revoke_route(provider: ChatProvider) -> CloudAiConsentStatusResponse:
    return revoke_cloud_ai_consent(provider)


@router.post("/ollama", response_model=OllamaChatResponse)
def ollama_chat_route(payload: OllamaChatRequest) -> OllamaChatResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_chat(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to generate chat response")
        raise HTTPException(status_code=500, detail="Failed to generate chat response.") from exc


@router.post("/ollama-stream")
def ollama_chat_stream_route(payload: OllamaChatRequest) -> StreamingResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        model, chunk_stream = ollama_chat_stream(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to start chat stream")
        raise HTTPException(status_code=500, detail="Failed to start chat stream.") from exc
    return StreamingResponse(
        chunk_stream,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Ollama-Model": model,
        },
    )


@router.post("/stream")
def chat_stream_route(payload: OllamaChatRequest) -> StreamingResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        provider, model, chunk_stream = chat_stream(payload)
    except CloudAiConsentRequired as exc:
        raise HTTPException(status_code=428, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to start chat stream")
        raise HTTPException(status_code=500, detail="Failed to start chat stream.") from exc
    return StreamingResponse(
        chunk_stream,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Chat-Provider": provider,
            "X-Chat-Model": model,
        },
    )


@router.post("/module-context", response_model=ModuleContextResponse)
def module_context_route(payload: ModuleContextRequest) -> ModuleContextResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return build_module_context(
            payload.moduleKey,
            workflow_hint=payload.workflow,
            mode_hint=payload.mode,
            context_tier=payload.contextTier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to build module context")
        raise HTTPException(status_code=500, detail="Failed to build module context.") from exc


@router.get("/model-capability", response_model=ModelCapabilityResponse)
def model_capability_route(
    model: str = Query(min_length=1),
    provider: ChatProvider = Query(default="ollama"),
    endpoint: str | None = Query(default=None),
) -> ModelCapabilityResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return model_capability(provider, model, endpoint_override=endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to inspect model capabilities")
        raise HTTPException(status_code=500, detail="Failed to inspect model capabilities.") from exc


@router.get("/gpu-status", response_model=OllamaGpuStatusResponse)
def ollama_gpu_status_route(endpoint: str | None = Query(default=None)) -> OllamaGpuStatusResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_gpu_status(endpoint_override=endpoint)
    except Exception as exc:
        LOGGER.exception("Failed to detect GPU status")
        raise HTTPException(status_code=500, detail="Failed to detect GPU status.") from exc


@router.get("/models", response_model=OllamaModelsResponse)
def ollama_models_route(endpoint: str | None = Query(default=None)) -> OllamaModelsResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_models(endpoint_override=endpoint)
    except Exception as exc:
        LOGGER.exception("Failed to load Ollama models")
        raise HTTPException(status_code=500, detail="Failed to load Ollama models.") from exc


@router.post("/models/install", response_model=OllamaModelManageResponse)
def ollama_models_install_route(payload: OllamaModelManageRequest) -> OllamaModelManageResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_install_model(payload.model, endpoint_override=payload.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to install Ollama model")
        raise HTTPException(status_code=500, detail="Failed to install Ollama model.") from exc


@router.post("/models/remove", response_model=OllamaModelManageResponse)
def ollama_models_remove_route(payload: OllamaModelManageRequest) -> OllamaModelManageResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_remove_model(payload.model, endpoint_override=payload.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to remove Ollama model")
        raise HTTPException(status_code=500, detail="Failed to remove Ollama model.") from exc

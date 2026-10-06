from __future__ import annotations

import logging
import anyio
from threading import Event

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.chat import (
    ChatProvider,
    CloudAiConsentStatusResponse,
    CloudAiConsentVersionRequest,
    ModelCapabilityResponse,
    OllamaGpuStatusResponse,
    OllamaModelManageRequest,
    OllamaModelManageResponse,
    OllamaModelsResponse,
)
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.services.scientific_assistant import assistant_step
from app.services.chat_tools import (
    ai_mode_enabled,
    model_capability,
    ollama_gpu_status,
    ollama_install_model,
    ollama_models,
    ollama_remove_model,
    provider_default_models,
)
from app.services.cloud_ai_consent import (
    CloudAiConsentRequired,
    cloud_ai_consent_status,
    grant_cloud_ai_consent,
    revoke_cloud_ai_consent,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/assistant", response_model=AssistantResponse)
async def scientific_assistant_route(payload: AssistantRequest, request: Request):
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        cancelled = Event()
        async def watch_disconnect():
            while not cancelled.is_set():
                if await request.is_disconnected():
                    cancelled.set()
                    return
                await anyio.sleep(0.2)
        error = None
        async with anyio.create_task_group() as group:
            group.start_soon(watch_disconnect)
            try:
                result = await anyio.to_thread.run_sync(lambda: assistant_step(payload, cancelled))
            except Exception as exc:
                error = exc
            finally:
                group.cancel_scope.cancel()
        if error is not None:
            raise error
        return result
    except CloudAiConsentRequired as exc:
        raise HTTPException(status_code=428, detail=exc.detail()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Scientific assistant failed")
        raise HTTPException(status_code=500, detail="The assistant could not complete this step.") from exc


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


@router.get("/provider-defaults")
def provider_defaults_route() -> dict[str, dict[str, str]]:
    """The cloud default models, so the browser does not keep its own copy."""
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    return {"models": provider_default_models()}


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

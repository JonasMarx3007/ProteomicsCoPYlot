from __future__ import annotations

import logging
import re
import anyio
from threading import Event

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.chat import (
    AiOperatorPolicyResponse,
    ChatProvider,
    CloudAiConsentStatusResponse,
    CloudAiConsentVersionRequest,
    LocalServerModelsRequest,
    ModelCapabilityResponse,
    OllamaGpuStatusResponse,
    OllamaModelManageRequest,
    OllamaModelManageResponse,
    OllamaModelsResponse,
    ProviderDefaultsResponse,
)
from app.schemas.assistant import AssistantProgressResponse, AssistantRequest, AssistantResponse
from app.services import assistant_progress
from app.services.scientific_assistant import assistant_step
from app.services.chat_tools import (
    ai_mode_enabled,
    ai_operator_policy,
    local_server_models,
    model_capability,
    ollama_gpu_status,
    ollama_install_model,
    ollama_model_management_allowed,
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


@router.get("/assistant-progress/{progress_id}", response_model=AssistantProgressResponse)
def assistant_progress_route(progress_id: str):
    """Phase and token count of a running assistant step (no content)."""
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", progress_id):
        raise HTTPException(status_code=400, detail="Invalid progress id.")
    return AssistantProgressResponse(**assistant_progress.read(progress_id))


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


@router.get("/provider-defaults", response_model=ProviderDefaultsResponse)
def provider_defaults_route() -> ProviderDefaultsResponse:
    """The cloud default models, so the browser does not keep its own copy."""
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    from app.services.local_ai_server import default_server_url

    return ProviderDefaultsResponse(
        models=provider_default_models(), policy=AiOperatorPolicyResponse(**ai_operator_policy()),
        localServerUrl=default_server_url(),
    )


@router.post("/local-models", response_model=OllamaModelsResponse)
def local_server_models_route(payload: LocalServerModelsRequest) -> OllamaModelsResponse:
    """Models of a local OpenAI-compatible server. A POST, so a typed API key
    never ends up in a URL or an access log."""
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return local_server_models(payload.endpoint, payload.apiKey)
    except Exception as exc:
        LOGGER.exception("Failed to load the local AI server's models")
        raise HTTPException(status_code=500, detail="Failed to load the local AI server's models.") from exc


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
    if not ollama_model_management_allowed():
        raise HTTPException(status_code=403, detail="Model management is reserved for the server operator.")
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
    if not ollama_model_management_allowed():
        raise HTTPException(status_code=403, detail="Model management is reserved for the server operator.")
    try:
        return ollama_remove_model(payload.model, endpoint_override=payload.endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to remove Ollama model")
        raise HTTPException(status_code=500, detail="Failed to remove Ollama model.") from exc

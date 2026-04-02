from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.chat import (
    ModuleContextRequest,
    ModuleContextResponse,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaGpuStatusResponse,
    OllamaModelsResponse,
)
from app.services.ai_context_tools import build_module_context
from app.services.chat_tools import (
    ai_mode_enabled,
    ollama_chat,
    ollama_chat_stream,
    ollama_gpu_status,
    ollama_models,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/ollama", response_model=OllamaChatResponse)
async def ollama_chat_route(payload: OllamaChatRequest) -> OllamaChatResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_chat(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate chat response: {exc}") from exc


@router.post("/ollama-stream")
async def ollama_chat_stream_route(payload: OllamaChatRequest) -> StreamingResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        model, chunk_stream = ollama_chat_stream(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start chat stream: {exc}") from exc
    return StreamingResponse(
        chunk_stream,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Ollama-Model": model,
        },
    )


@router.post("/module-context", response_model=ModuleContextResponse)
async def module_context_route(payload: ModuleContextRequest) -> ModuleContextResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return build_module_context(payload.moduleKey)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build module context: {exc}") from exc


@router.get("/gpu-status", response_model=OllamaGpuStatusResponse)
async def ollama_gpu_status_route() -> OllamaGpuStatusResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_gpu_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to detect GPU status: {exc}") from exc


@router.get("/models", response_model=OllamaModelsResponse)
async def ollama_models_route() -> OllamaModelsResponse:
    if not ai_mode_enabled():
        raise HTTPException(status_code=404, detail="AI features are disabled for this app mode.")
    try:
        return ollama_models()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load Ollama models: {exc}") from exc

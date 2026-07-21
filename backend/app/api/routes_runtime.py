from __future__ import annotations

from fastapi import APIRouter

from app.schemas.runtime import RRuntimeStatusResponse
from app.services.r_runtime import clear_r_runtime_cache, detect_r_runtime

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/r", response_model=RRuntimeStatusResponse)
async def r_runtime_status_route(refresh: bool = False) -> RRuntimeStatusResponse:
    if refresh:
        clear_r_runtime_cache()
    return RRuntimeStatusResponse(**detect_r_runtime())

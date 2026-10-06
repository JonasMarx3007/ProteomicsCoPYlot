from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.analysis import AnalysisVolcanoRequest, AnalysisVolcanoResponse
from app.services.analysis_functions import analysis_volcano_data

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/volcano/data", response_model=AnalysisVolcanoResponse)
def analysis_volcano_data_route(payload: AnalysisVolcanoRequest) -> AnalysisVolcanoResponse:
    try:
        return analysis_volcano_data(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load analysis volcano data")
        raise HTTPException(status_code=500, detail="Failed to load analysis volcano data.") from e

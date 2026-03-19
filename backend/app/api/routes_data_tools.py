from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import (
    DistributionSummaryResponse,
    ImputationResultResponse,
    ImputationRunRequest,
    VerificationSummaryResponse,
)
from app.services.data_tools import distribution_summary, run_imputation, verification_summary

router = APIRouter(prefix="/api/data-tools", tags=["data-tools"])


@router.post("/imputation/run", response_model=ImputationResultResponse)
async def run_imputation_route(payload: ImputationRunRequest) -> ImputationResultResponse:
    try:
        return run_imputation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Imputation failed: {e}") from e


@router.get("/distribution/{kind}", response_model=DistributionSummaryResponse)
async def distribution_route(
    kind: AnnotationKind,
) -> DistributionSummaryResponse:
    try:
        return distribution_summary(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Distribution analysis failed: {e}") from e


@router.get("/verification/{kind}", response_model=VerificationSummaryResponse)
async def verification_route(kind: AnnotationKind) -> VerificationSummaryResponse:
    try:
        return verification_summary(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification analysis failed: {e}") from e

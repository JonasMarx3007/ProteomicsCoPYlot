from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.annotation import AnnotationKind
from app.schemas.qc import QcSummaryResponse
from app.services.qc_tools import qc_summary

router = APIRouter(prefix="/api/qc", tags=["qc"])


@router.get("/summary/{kind}", response_model=QcSummaryResponse)
async def qc_summary_route(kind: AnnotationKind) -> QcSummaryResponse:
    try:
        return qc_summary(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QC summary failed: {e}") from e


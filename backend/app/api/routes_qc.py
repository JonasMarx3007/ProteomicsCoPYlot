from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.annotation import AnnotationKind
from app.schemas.qc import QcSummaryResponse
from app.services.qc_tools import qc_summary

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/qc", tags=["qc"])


@router.get("/summary/{kind}", response_model=QcSummaryResponse)
def qc_summary_route(kind: AnnotationKind) -> QcSummaryResponse:
    try:
        return qc_summary(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("QC summary failed")
        raise HTTPException(status_code=500, detail="QC summary failed.") from e

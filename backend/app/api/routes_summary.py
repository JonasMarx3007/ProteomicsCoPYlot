from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.summary import (
    SummaryReportRequest,
    SummaryReportResponse,
    SummaryTablesResponse,
)
from app.services.report_function import report_function
from app.services.summary_tools import summary_tables

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("/tables", response_model=SummaryTablesResponse)
async def summary_tables_route() -> SummaryTablesResponse:
    try:
        return summary_tables()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load summary tables: {e}") from e


@router.post("/report", response_model=SummaryReportResponse)
async def summary_report_route(payload: SummaryReportRequest) -> SummaryReportResponse:
    try:
        return report_function(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build report: {e}") from e

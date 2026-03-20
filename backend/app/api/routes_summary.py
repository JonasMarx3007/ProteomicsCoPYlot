from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.schemas.summary import SummaryOverviewResponse, SummaryReportRequest
from app.services.report_functions import build_summary_overview, generate_summary_html

router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("/overview", response_model=SummaryOverviewResponse)
async def summary_overview_route() -> SummaryOverviewResponse:
    try:
        return build_summary_overview()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build summary overview: {e}") from e


@router.post("/report/download")
async def summary_report_download_route(payload: SummaryReportRequest) -> Response:
    try:
        html_bytes, filename = generate_summary_html(payload)
        return Response(
            content=html_bytes,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary report: {e}") from e

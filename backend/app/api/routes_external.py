from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.external import PeptideCollapseRequest, PeptideCollapseResponse
from app.services.external_tools import run_peptide_collapse

router = APIRouter(prefix="/api/external", tags=["external"])


@router.post("/peptide-collapse/run", response_model=PeptideCollapseResponse)
async def run_peptide_collapse_route(payload: PeptideCollapseRequest) -> PeptideCollapseResponse:
    try:
        return run_peptide_collapse(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Peptide collapse failed: {e}") from e

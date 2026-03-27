from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import (
    EnrichmentRequest,
    EnrichmentResultResponse,
    ListEnrichmentRequest,
    ListEnrichmentResultResponse,
    PathwayOptionsResponse,
    SimulationRequest,
    SimulationResultResponse,
    StatisticalOptionsResponse,
    VolcanoControlRequest,
    VolcanoResultResponse,
    VolcanoRequest,
)
from app.services.stats_tools import (
    pathway_options,
    run_enrichment_from_list,
    run_enrichment,
    run_simulation,
    run_volcano,
    run_volcano_control,
    statistical_options,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/options/{kind}", response_model=StatisticalOptionsResponse)
async def stats_options_route(kind: AnnotationKind) -> StatisticalOptionsResponse:
    try:
        return statistical_options(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load statistical options: {e}") from e


@router.post("/volcano/run", response_model=VolcanoResultResponse)
async def volcano_route(payload: VolcanoRequest) -> VolcanoResultResponse:
    try:
        return run_volcano(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run volcano analysis: {e}") from e


@router.post("/volcano-control/run", response_model=VolcanoResultResponse)
async def volcano_control_route(payload: VolcanoControlRequest) -> VolcanoResultResponse:
    try:
        return run_volcano_control(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run control volcano analysis: {e}") from e


@router.post("/gsea/run", response_model=EnrichmentResultResponse)
async def gsea_route(payload: EnrichmentRequest) -> EnrichmentResultResponse:
    try:
        return run_enrichment(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run enrichment analysis: {e}") from e


@router.post("/gsea/list/run", response_model=ListEnrichmentResultResponse)
async def gsea_list_route(payload: ListEnrichmentRequest) -> ListEnrichmentResultResponse:
    try:
        return run_enrichment_from_list(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run list enrichment analysis: {e}") from e


@router.get("/pathways", response_model=PathwayOptionsResponse)
async def pathway_options_route() -> PathwayOptionsResponse:
    try:
        return pathway_options()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load pathway options: {e}") from e


@router.post("/simulation/run", response_model=SimulationResultResponse)
async def simulation_route(payload: SimulationRequest) -> SimulationResultResponse:
    try:
        return run_simulation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run simulation: {e}") from e

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import (
    AnovaRequest,
    AnovaResultResponse,
    EnrichmentOrganism,
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
    run_anova,
    pathway_options,
    run_enrichment_from_list,
    run_enrichment,
    run_simulation,
    run_volcano,
    run_volcano_control,
    statistical_options,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/options/{kind}", response_model=StatisticalOptionsResponse)
def stats_options_route(kind: AnnotationKind) -> StatisticalOptionsResponse:
    try:
        return statistical_options(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load statistical options")
        raise HTTPException(status_code=500, detail="Failed to load statistical options.") from e


@router.post("/volcano/run", response_model=VolcanoResultResponse)
def volcano_route(payload: VolcanoRequest) -> VolcanoResultResponse:
    try:
        return run_volcano(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run volcano analysis")
        raise HTTPException(status_code=500, detail="Failed to run volcano analysis.") from e


@router.post("/volcano-control/run", response_model=VolcanoResultResponse)
def volcano_control_route(payload: VolcanoControlRequest) -> VolcanoResultResponse:
    try:
        return run_volcano_control(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run control volcano analysis")
        raise HTTPException(status_code=500, detail="Failed to run control volcano analysis.") from e


@router.post("/anova/run", response_model=AnovaResultResponse)
def anova_route(payload: AnovaRequest) -> AnovaResultResponse:
    try:
        return run_anova(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run ANOVA analysis")
        raise HTTPException(status_code=500, detail="Failed to run ANOVA analysis.") from e


@router.post("/ora/run", response_model=EnrichmentResultResponse)
def ora_route(payload: EnrichmentRequest) -> EnrichmentResultResponse:
    try:
        return run_enrichment(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run enrichment analysis")
        raise HTTPException(status_code=500, detail="Failed to run enrichment analysis.") from e


@router.post("/ora/list/run", response_model=ListEnrichmentResultResponse)
def ora_list_route(payload: ListEnrichmentRequest) -> ListEnrichmentResultResponse:
    try:
        from app.services.assistant_snapshots import store_snapshot
        result = run_enrichment_from_list(payload)
        data = result.model_dump(exclude={"evidenceToken", "terms", "genes", "backgroundGenes"})
        data.update(type="canvas_ora", querySize=len(result.genes), totalRows=len(result.terms),
                    terms=[term.model_dump() for term in result.terms[:10]],
                    settings=payload.model_dump(exclude={"genes", "backgroundGenes"}))
        result.evidenceToken = store_snapshot(data)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run list enrichment analysis")
        raise HTTPException(status_code=500, detail="Failed to run list enrichment analysis.") from e


@router.get("/pathways", response_model=PathwayOptionsResponse)
def pathway_options_route(organism: EnrichmentOrganism = "human") -> PathwayOptionsResponse:
    try:
        return pathway_options(organism)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load pathway options")
        raise HTTPException(status_code=500, detail="Failed to load pathway options.") from e


@router.post("/simulation/run", response_model=SimulationResultResponse)
def simulation_route(payload: SimulationRequest) -> SimulationResultResponse:
    try:
        return run_simulation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to run simulation")
        raise HTTPException(status_code=500, detail="Failed to run simulation.") from e

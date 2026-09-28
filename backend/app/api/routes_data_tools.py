from __future__ import annotations

import logging

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import (
    ConditionPaletteResponse,
    ConditionPaletteUpdateRequest,
    DistributionSummaryResponse,
    IdTranslationRequest,
    IdTranslationResponse,
    ImputationResultResponse,
    ImputationRunRequest,
)
from app.schemas.completeness import CompletenessTablesResponse
from app.services.completeness_tools import (
    completeness_tables,
)
from app.services.data_tools import (
    distribution_summary,
    export_id_translation,
    get_condition_palette_config,
    imputed_dataframe,
    update_condition_palette_config,
    run_id_translation,
    run_imputation,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/data-tools", tags=["data-tools"])


@router.post("/imputation/run", response_model=ImputationResultResponse)
def run_imputation_route(payload: ImputationRunRequest) -> ImputationResultResponse:
    try:
        return run_imputation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Imputation failed")
        raise HTTPException(status_code=500, detail="Imputation failed.") from e


@router.post("/imputation/download")
def download_imputation_route(payload: ImputationRunRequest) -> StreamingResponse:
    try:
        frame = imputed_dataframe(payload)
        csv_bytes = frame.to_csv(index=False).encode("utf-8")
        buffer = io.BytesIO(csv_bytes)
        filename = (
            f"imputed_{payload.kind}"
            f"_{payload.method}"
            f"_q{payload.qValue}"
            f"_std{payload.adjustStd}"
            f"_down{payload.downShift}"
            f"_width{payload.width}"
            f"_seed{payload.seed}"
            f"_samplewise{int(payload.sampleWise)}.csv"
        )
        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Imputation download failed")
        raise HTTPException(status_code=500, detail="Imputation download failed.") from e


@router.get("/distribution/{kind}", response_model=DistributionSummaryResponse)
def distribution_route(
    kind: AnnotationKind,
) -> DistributionSummaryResponse:
    try:
        return distribution_summary(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Distribution analysis failed")
        raise HTTPException(status_code=500, detail="Distribution analysis failed.") from e


@router.get("/completeness/{kind}/tables", response_model=CompletenessTablesResponse)
def completeness_tables_route(
    kind: AnnotationKind,
    outlierThreshold: float = 50.0,
    includeId: bool = True,
) -> CompletenessTablesResponse:
    try:
        return completeness_tables(
            kind=kind,
            outlier_threshold=outlierThreshold,
            include_id=includeId,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Completeness analysis failed")
        raise HTTPException(status_code=500, detail="Completeness analysis failed.") from e


@router.post("/id-translation/run", response_model=IdTranslationResponse)
def id_translation_route(payload: IdTranslationRequest) -> IdTranslationResponse:
    try:
        return run_id_translation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("ID translation failed")
        raise HTTPException(status_code=500, detail="ID translation failed.") from e


@router.post("/id-translation/download")
def download_id_translation_route(payload: IdTranslationRequest) -> StreamingResponse:
    try:
        filename, content, media_type = export_id_translation(payload)
        buffer = io.BytesIO(content)
        return StreamingResponse(
            buffer,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("ID translation download failed")
        raise HTTPException(status_code=500, detail="ID translation download failed.") from e


@router.get("/condition-colors/{kind}", response_model=ConditionPaletteResponse)
def get_condition_colors_route(kind: AnnotationKind) -> ConditionPaletteResponse:
    try:
        return get_condition_palette_config(kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load condition colors")
        raise HTTPException(status_code=500, detail="Failed to load condition colors.") from e


@router.post("/condition-colors/{kind}", response_model=ConditionPaletteResponse)
def set_condition_colors_route(
    kind: AnnotationKind,
    payload: ConditionPaletteUpdateRequest,
) -> ConditionPaletteResponse:
    try:
        return update_condition_palette_config(kind, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to save condition colors")
        raise HTTPException(status_code=500, detail="Failed to save condition colors.") from e

from __future__ import annotations

import logging

import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import (
    PhosphoLocalizationCutoffRequest,
    PhosphoLocalizationCutoffResponse,
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
from app.api.download_headers import attachment_disposition

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
            headers={"Content-Disposition": attachment_disposition(filename)},
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
    snapshot: str = "",
) -> CompletenessTablesResponse:
    if snapshot:
        from app.services.notebook_completeness import snapshot_tables
        return snapshot_tables(kind, snapshot, include_id=includeId, outlier_threshold=outlierThreshold)
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
            headers={"Content-Disposition": attachment_disposition(filename)},
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


def _localization_cutoff_response() -> PhosphoLocalizationCutoffResponse:
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import get_current_dataset
    from app.services.functions import LOCALIZATION_COLUMN
    from app.services.phospho_localization import get_localization_cutoff

    annotation = get_annotation("phospho")
    frame = getattr(annotation, "source_data", None) if annotation is not None else None
    if frame is None or getattr(frame, "empty", True):
        dataset = get_current_dataset("phospho")
        frame = getattr(dataset, "frame", None)
    available = frame is not None and LOCALIZATION_COLUMN in frame.columns
    return PhosphoLocalizationCutoffResponse(cutoff=get_localization_cutoff(), available=bool(available))


@router.get("/phospho-localization-cutoff", response_model=PhosphoLocalizationCutoffResponse)
def get_phospho_localization_cutoff_route() -> PhosphoLocalizationCutoffResponse:
    return _localization_cutoff_response()


@router.post("/phospho-localization-cutoff", response_model=PhosphoLocalizationCutoffResponse)
def set_phospho_localization_cutoff_route(
    payload: PhosphoLocalizationCutoffRequest,
) -> PhosphoLocalizationCutoffResponse:
    from app.services.phospho_localization import set_localization_cutoff

    try:
        set_localization_cutoff(payload.cutoff)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _localization_cutoff_response()

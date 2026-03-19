from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationGenerateRequest,
    AnnotationKind,
    AnnotationResultResponse,
)
from app.services.annotation_processor import compute_annotation
from app.services.annotation_store import get_annotation, save_annotation
from app.services.dataset_store import get_current_dataset

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


def _to_preview(df: pd.DataFrame, max_rows: int) -> list[dict[str, object]]:
    subset = df.head(max_rows).where(pd.notna(df.head(max_rows)), None)
    return subset.to_dict(orient="records")


def _response_from_stored(stored) -> AnnotationResultResponse:
    return AnnotationResultResponse(
        kind=stored.kind,
        sourceRows=len(stored.source_data),
        sourceColumns=len(stored.source_data.columns),
        metadataRows=len(stored.metadata),
        conditionCount=int(stored.metadata["condition"].nunique()),
        sampleCount=len(stored.metadata["sample"]),
        metadataPreview=_to_preview(stored.metadata, max_rows=30),
        log2Rows=len(stored.log2_data),
        log2Columns=len(stored.log2_data.columns),
        filteredRows=len(stored.filtered_data),
        filteredColumns=len(stored.filtered_data.columns),
        filteredPreview=_to_preview(stored.filtered_data, max_rows=20),
        isLog2Transformed=stored.is_log2_transformed,
        filter=stored.filter_config,
        autoDetected=stored.auto_detected,
        warnings=stored.warnings,
    )


@router.post("/generate", response_model=AnnotationResultResponse)
async def generate_annotation(payload: AnnotationGenerateRequest) -> AnnotationResultResponse:
    current_dataset = get_current_dataset(payload.kind)
    if current_dataset is None or not hasattr(current_dataset, "frame"):
        raise HTTPException(
            status_code=400,
            detail=f"No {payload.kind} dataset is currently loaded. Upload data first.",
        )

    filter_config = payload.filter or AnnotationFilterConfig()

    try:
        computed = compute_annotation(
            data=current_dataset.frame,
            conditions=payload.conditions,
            is_log2_transformed=payload.isLog2Transformed,
            min_present=filter_config.minPresent,
            filter_mode=filter_config.mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate annotation: {e}") from e

    stored = save_annotation(
        kind=payload.kind,
        source_data=current_dataset.frame,
        metadata=computed.metadata,
        log2_data=computed.log2_data,
        filtered_data=computed.filtered_data,
        is_log2_transformed=payload.isLog2Transformed,
        filter_config=filter_config,
        auto_detected=computed.auto_detected,
        warnings=computed.warnings,
    )

    return _response_from_stored(stored)


@router.get("/current/{kind}", response_model=AnnotationResultResponse)
async def get_current_annotation(kind: AnnotationKind) -> AnnotationResultResponse:
    stored = get_annotation(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No annotation stored for {kind} dataset")

    return _response_from_stored(stored)


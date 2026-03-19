from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationGenerateRequest,
    AnnotationKind,
    MetadataUploadResponse,
    AnnotationResultResponse,
)
from app.services.annotation_processor import (
    compute_annotation,
    compute_annotation_from_metadata,
)
from app.services.annotation_store import get_annotation, save_annotation
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.dataset_store import get_current_dataset
from app.services.metadata_upload_store import (
    clear_uploaded_metadata,
    get_uploaded_metadata,
    save_uploaded_metadata,
)

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
        metadataSource=getattr(stored, "metadata_source", "manual"),
        filter=stored.filter_config,
        autoDetected=stored.auto_detected,
        warnings=stored.warnings,
    )


def _metadata_upload_response(stored) -> MetadataUploadResponse:
    preview = stored.frame.head(30).where(pd.notna(stored.frame.head(30)), None)
    return MetadataUploadResponse(
        kind=stored.kind,
        filename=stored.filename,
        rows=len(stored.frame),
        columns=len(stored.frame.columns),
        createdAt=stored.created_at,
        preview=preview.to_dict(orient="records"),
    )


@router.post("/metadata/upload", response_model=MetadataUploadResponse)
async def upload_annotation_metadata(
    file: UploadFile = File(...),
    kind: AnnotationKind = Form(...),
) -> MetadataUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        _ = get_extension(file.filename)
        frame = read_dataframe(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse metadata file: {e}") from e

    stored = save_uploaded_metadata(kind=kind, filename=file.filename, frame=frame)
    return _metadata_upload_response(stored)


@router.get("/metadata/current/{kind}", response_model=MetadataUploadResponse)
async def get_current_uploaded_metadata(kind: AnnotationKind) -> MetadataUploadResponse:
    stored = get_uploaded_metadata(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No uploaded metadata stored for {kind} dataset")
    return _metadata_upload_response(stored)


@router.delete("/metadata/current/{kind}")
async def clear_current_uploaded_metadata(kind: AnnotationKind) -> dict[str, object]:
    clear_uploaded_metadata(kind)
    return {"kind": kind, "cleared": True}


@router.post("/generate", response_model=AnnotationResultResponse)
async def generate_annotation(payload: AnnotationGenerateRequest) -> AnnotationResultResponse:
    current_dataset = get_current_dataset(payload.kind)
    if current_dataset is None or not hasattr(current_dataset, "frame"):
        raise HTTPException(
            status_code=400,
            detail=f"No {payload.kind} dataset is currently loaded. Upload data first.",
        )

    filter_config = payload.filter or AnnotationFilterConfig()

    uploaded_metadata = get_uploaded_metadata(payload.kind)

    try:
        if uploaded_metadata is not None:
            computed = compute_annotation_from_metadata(
                data=current_dataset.frame,
                metadata=uploaded_metadata.frame,
                is_log2_transformed=payload.isLog2Transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = "uploaded"
        else:
            computed = compute_annotation(
                data=current_dataset.frame,
                conditions=payload.conditions,
                is_log2_transformed=payload.isLog2Transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
            )
            metadata_source = "auto" if computed.auto_detected else "manual"
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
        metadata_source=metadata_source,
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

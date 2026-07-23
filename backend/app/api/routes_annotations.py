from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationGenerateRequest,
    AnnotationKind,
    AnnotationResultResponse,
    Log2DetectionRequest,
    Log2DetectionResponse,
    MetadataAnnotationKind,
    MetadataUploadResponse,
    PhosprotAggregateRequest,
)
from app.services.annotation_processor import (
    compute_annotation,
    compute_annotation_from_metadata,
    detect_log2_transformed,
    normalize_uploaded_metadata,
)
from app.services.annotation_store import clear_annotation, get_annotation, save_annotation
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.dataset_store import get_current_dataset
from app.services.metadata_upload_store import (
    get_active_profile,
    clear_uploaded_metadata,
    get_uploaded_metadata,
    list_auto_generated_profiles,
    save_uploaded_metadata,
)
from app.services.phosprot_tools import aggregate_from_phospho, upload_phosprot

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
        log2AutoDetected=getattr(stored, "log2_auto_detected", False),
        metadataSource=getattr(stored, "metadata_source", "manual"),
        filter=stored.filter_config,
        autoDetected=stored.auto_detected,
        warnings=stored.warnings,
        imputation=getattr(stored, "imputation", None),
    )


def _metadata_upload_response(stored) -> MetadataUploadResponse:
    preview = stored.frame.head(30).where(pd.notna(stored.frame.head(30)), None)
    return MetadataUploadResponse(
        kind=stored.kind,
        profileName=get_active_profile(),
        filename=stored.filename,
        rows=len(stored.frame),
        columns=len(stored.frame.columns),
        createdAt=stored.created_at,
        preview=preview.to_dict(orient="records"),
    )


def _stream_dataframe_download(
    frame: pd.DataFrame,
    *,
    filename: str,
    error_detail: str,
) -> StreamingResponse:
    try:
        csv_bytes = frame.to_csv(index=False).encode("utf-8")
        buffer = io.BytesIO(csv_bytes)
        return StreamingResponse(
            buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{error_detail}: {e}") from e


def _sync_auto_generated_profile_annotations(kind: MetadataAnnotationKind) -> None:
    current_dataset = get_current_dataset(kind)
    if current_dataset is None or not hasattr(current_dataset, "frame"):
        return

    base_annotation = get_annotation(kind)
    if base_annotation is not None:
        is_log2_transformed = (
            None
            if getattr(base_annotation, "log2_auto_detected", False)
            else base_annotation.is_log2_transformed
        )
        filter_config = base_annotation.filter_config
    else:
        is_log2_transformed = None
        filter_config = AnnotationFilterConfig()

    for profile_name in list_auto_generated_profiles():
        uploaded_metadata = get_uploaded_metadata(kind, profile_name=profile_name)
        if uploaded_metadata is None or uploaded_metadata.frame.empty:
            clear_annotation(kind, metadata_profile_name=profile_name)
            continue

        computed = compute_annotation_from_metadata(
            data=current_dataset.frame,
            metadata=uploaded_metadata.frame,
            is_log2_transformed=is_log2_transformed,
            min_present=filter_config.minPresent,
            filter_mode=filter_config.mode,
            filter_method=filter_config.method,
            min_percentage=filter_config.minPercentage,
        )
        save_annotation(
            kind=kind,
            source_data=current_dataset.frame,
            metadata=computed.metadata,
            log2_data=computed.log2_data,
            filtered_data=computed.filtered_data,
            is_log2_transformed=computed.is_log2_transformed,
            metadata_source="uploaded",
            filter_config=filter_config,
            auto_detected=computed.auto_detected,
            warnings=computed.warnings,
            log2_auto_detected=computed.log2_auto_detected,
            metadata_profile_name=profile_name,
        )


@router.post("/metadata/upload", response_model=MetadataUploadResponse)
async def upload_annotation_metadata(
    file: UploadFile = File(...),
    kind: MetadataAnnotationKind = Form(...),
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
    _sync_auto_generated_profile_annotations(kind)
    return _metadata_upload_response(stored)


@router.get("/metadata/current/{kind}", response_model=MetadataUploadResponse)
async def get_current_uploaded_metadata(kind: MetadataAnnotationKind) -> MetadataUploadResponse:
    stored = get_uploaded_metadata(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No uploaded metadata stored for {kind} dataset")
    return _metadata_upload_response(stored)


@router.delete("/metadata/current/{kind}")
async def clear_current_uploaded_metadata(kind: MetadataAnnotationKind) -> dict[str, object]:
    clear_uploaded_metadata(kind)
    _sync_auto_generated_profile_annotations(kind)
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

    metadata_kind: MetadataAnnotationKind | None
    if payload.kind == "protein":
        metadata_kind = "protein"
    elif payload.kind in {"phospho", "phosprot"}:
        metadata_kind = "phospho"
    else:
        metadata_kind = None

    uploaded_metadata = (
        get_uploaded_metadata(metadata_kind)
        if metadata_kind is not None
        else None
    )

    try:
        if uploaded_metadata is not None:
            computed = compute_annotation_from_metadata(
                data=current_dataset.frame,
                metadata=uploaded_metadata.frame,
                is_log2_transformed=payload.isLog2Transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
                filter_method=filter_config.method,
                min_percentage=filter_config.minPercentage,
            )
            metadata_source = "shared_phospho" if payload.kind == "phosprot" else "uploaded"
        else:
            computed = compute_annotation(
                data=current_dataset.frame,
                conditions=payload.conditions,
                is_log2_transformed=payload.isLog2Transformed,
                min_present=filter_config.minPresent,
                filter_mode=filter_config.mode,
                filter_method=filter_config.method,
                min_percentage=filter_config.minPercentage,
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
        is_log2_transformed=computed.is_log2_transformed,
        metadata_source=metadata_source,
        filter_config=filter_config,
        auto_detected=computed.auto_detected,
        warnings=computed.warnings,
        log2_auto_detected=computed.log2_auto_detected,
    )

    return _response_from_stored(stored)


@router.get("/current/{kind}", response_model=AnnotationResultResponse)
async def get_current_annotation(kind: AnnotationKind) -> AnnotationResultResponse:
    stored = get_annotation(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No annotation stored for {kind} dataset")

    return _response_from_stored(stored)


@router.post("/log2-detect", response_model=Log2DetectionResponse)
async def detect_annotation_log2_scale(
    payload: Log2DetectionRequest,
) -> Log2DetectionResponse:
    current_dataset = get_current_dataset(payload.kind)
    if current_dataset is None or not hasattr(current_dataset, "frame"):
        raise HTTPException(
            status_code=400,
            detail=f"No {payload.kind} dataset is currently loaded. Upload data first.",
        )

    metadata_kind: MetadataAnnotationKind = (
        "protein" if payload.kind == "protein" else "phospho"
    )
    uploaded_metadata = get_uploaded_metadata(metadata_kind)
    if uploaded_metadata is not None:
        try:
            normalized = normalize_uploaded_metadata(
                data=current_dataset.frame,
                metadata=uploaded_metadata.frame,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sample_columns = normalized["sample"].astype(str).tolist()
    else:
        requested = [str(column) for column in payload.sampleColumns]
        available = set(str(column) for column in current_dataset.frame.columns)
        sample_columns = list(dict.fromkeys(column for column in requested if column in available))

    detection = detect_log2_transformed(current_dataset.frame, sample_columns)
    return Log2DetectionResponse(
        isLog2Transformed=detection.is_log2_transformed,
        sampleCount=len(sample_columns),
        reason=detection.reason,
    )


@router.get("/current/{kind}/filtered/download")
async def download_current_filtered_annotation(kind: AnnotationKind) -> StreamingResponse:
    stored = get_annotation(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No annotation stored for {kind} dataset")

    return _stream_dataframe_download(
        stored.filtered_data,
        filename=f"{kind}_filtered_data_full.csv",
        error_detail="Failed to download filtered annotation data",
    )


@router.get("/current/{kind}/source/download")
async def download_current_source_annotation(kind: AnnotationKind) -> StreamingResponse:
    stored = get_annotation(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No annotation stored for {kind} dataset")

    return _stream_dataframe_download(
        stored.source_data,
        filename=f"{kind}_data_full.csv",
        error_detail="Failed to download non-filtered annotation data",
    )


@router.get("/current/{kind}/metadata/download")
async def download_current_metadata_annotation(kind: AnnotationKind) -> StreamingResponse:
    stored = get_annotation(kind)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No annotation stored for {kind} dataset")

    return _stream_dataframe_download(
        stored.metadata,
        filename=f"{kind}_metadata_full.csv",
        error_detail="Failed to download metadata annotation data",
    )


@router.post("/phosprot/aggregate", response_model=AnnotationResultResponse)
async def aggregate_phosprot_annotation(
    payload: PhosprotAggregateRequest,
) -> AnnotationResultResponse:
    try:
        stored = aggregate_from_phospho(mode=payload.mode, source=payload.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to aggregate phosphoprotein dataset: {e}",
        ) from e
    return _response_from_stored(stored)


@router.post("/phosprot/upload", response_model=AnnotationResultResponse)
async def upload_phosprot_annotation(
    file: UploadFile = File(...),
    isLog2Transformed: bool | None = Form(default=None),
) -> AnnotationResultResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        _ = get_extension(file.filename)
        frame = read_dataframe(file.filename, file.file)
        stored = upload_phosprot(
            frame=frame,
            filename=file.filename,
            is_log2_transformed=isLog2Transformed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload phosphoprotein dataset: {e}",
        ) from e
    return _response_from_stored(stored)

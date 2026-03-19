from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.dataset import DatasetPreviewResponse
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.dataset_store import get_dataset, save_dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post("/upload", response_model=DatasetPreviewResponse)
async def upload_dataset(
    file: UploadFile = File(...),
    kind: Literal["protein", "phospho"] = Form(...),
) -> DatasetPreviewResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        _ = get_extension(file.filename)
        df = read_dataframe(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}") from e

    stored = save_dataset(file.filename, kind, df)

    return DatasetPreviewResponse(
        datasetId=stored.dataset_id,
        filename=stored.filename,
        kind=stored.kind,
        format=file.filename.split(".")[-1].lower(),
        rows=len(df),
        columns=len(df.columns),
        columnNames=[str(c) for c in df.columns],
        preview=df.head(20).replace({float("nan"): None}).to_dict(orient="records"),
    )


@router.get("/{dataset_id}", response_model=DatasetPreviewResponse)
async def get_dataset_preview(dataset_id: str) -> DatasetPreviewResponse:
    stored = get_dataset(dataset_id)
    if not stored:
        raise HTTPException(status_code=404, detail="Dataset not found")

    df = stored.frame
    ext = stored.filename.split(".")[-1].lower()

    return DatasetPreviewResponse(
        datasetId=stored.dataset_id,
        filename=stored.filename,
        kind=stored.kind,
        format=ext,
        rows=len(df),
        columns=len(df.columns),
        columnNames=[str(c) for c in df.columns],
        preview=df.head(20).replace({float("nan"): None}).to_dict(orient="records"),
    )
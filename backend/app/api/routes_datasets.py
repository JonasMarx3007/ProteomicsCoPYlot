from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.dataset import (
    CurrentDatasetsResponse,
    DatasetPreviewResponse,
    PeptidePathRequest,
    PeptidePathResponse,
)
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.dataset_store import (
    get_all_current_datasets,
    save_peptide_path,
    save_table_dataset,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _table_preview_response(stored) -> DatasetPreviewResponse:
    df = stored.frame
    return DatasetPreviewResponse(
        filename=stored.filename,
        kind=stored.kind,
        format=stored.filename.split(".")[-1].lower(),
        rows=len(df),
        columns=len(df.columns),
        columnNames=[str(c) for c in df.columns],
        preview=df.head(20).replace({float("nan"): None}).to_dict(orient="records"),
    )


def _peptide_response(stored) -> PeptidePathResponse:
    return PeptidePathResponse(
        filename=stored.filename,
        kind="peptide",
        format="path",
        path=stored.path,
        rows=0,
        columns=0,
        columnNames=[],
        preview=[],
    )


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

    stored = save_table_dataset(file.filename, kind, df)
    return _table_preview_response(stored)


@router.post("/peptide-path", response_model=PeptidePathResponse)
async def set_peptide_path(payload: PeptidePathRequest) -> PeptidePathResponse:
    if not payload.path.strip():
        raise HTTPException(status_code=400, detail="Path must not be empty")

    stored = save_peptide_path(payload.path)
    return _peptide_response(stored)


@router.get("/current", response_model=CurrentDatasetsResponse)
async def get_current_datasets() -> CurrentDatasetsResponse:
    current = get_all_current_datasets()

    protein = current["protein"]
    phospho = current["phospho"]
    peptide = current["peptide"]

    return CurrentDatasetsResponse(
        protein=_table_preview_response(protein) if protein else None,
        phospho=_table_preview_response(phospho) if phospho else None,
        peptide=_peptide_response(peptide) if peptide else None,
    )
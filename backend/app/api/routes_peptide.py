from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.peptide import (
    PeptideCoverageResponse,
    PeptideMetadataResponse,
    PeptideOverviewResponse,
    PeptideSpecies,
)
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.peptide_metadata_store import (
    clear_peptide_metadata,
    get_peptide_metadata,
    save_peptide_metadata,
)
from app.services.peptide_tools import peptide_overview, peptide_sequence_coverage

router = APIRouter(prefix="/api/peptide", tags=["peptide"])


def _metadata_response(stored) -> PeptideMetadataResponse:
    preview = stored.frame.head(30).where(pd.notna(stored.frame.head(30)), None)
    return PeptideMetadataResponse(
        filename=stored.filename,
        rows=len(stored.frame),
        columns=len(stored.frame.columns),
        createdAt=stored.created_at,
        preview=preview.to_dict(orient="records"),
    )


@router.get("/overview", response_model=PeptideOverviewResponse)
async def get_peptide_overview() -> PeptideOverviewResponse:
    try:
        return PeptideOverviewResponse(**peptide_overview())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load peptide overview: {e}") from e


@router.post("/metadata/upload", response_model=PeptideMetadataResponse)
async def upload_peptide_metadata(file: UploadFile = File(...)) -> PeptideMetadataResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        _ = get_extension(file.filename)
        frame = read_dataframe(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse metadata file: {e}") from e

    stored = save_peptide_metadata(file.filename, frame)
    return _metadata_response(stored)


@router.get("/metadata/current", response_model=PeptideMetadataResponse)
async def get_current_peptide_metadata() -> PeptideMetadataResponse:
    stored = get_peptide_metadata()
    if stored is None:
        raise HTTPException(status_code=404, detail="No peptide metadata is currently stored.")
    return _metadata_response(stored)


@router.delete("/metadata/current")
async def clear_current_peptide_metadata() -> dict[str, object]:
    clear_peptide_metadata()
    return {"cleared": True}


@router.get("/sequence-coverage", response_model=PeptideCoverageResponse)
async def get_sequence_coverage(
    species: PeptideSpecies,
    protein: str,
    chunkSize: int = 100,
) -> PeptideCoverageResponse:
    try:
        return PeptideCoverageResponse(
            **peptide_sequence_coverage(species=species, protein=protein, chunk_size=chunkSize)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate sequence coverage: {e}") from e

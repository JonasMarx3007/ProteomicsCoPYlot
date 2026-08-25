from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.peptide import (
    PeptideCoverageResponse,
    PeptideMetadataGenerateRequest,
    PeptideMetadataResponse,
    PeptideOverviewResponse,
    PeptideQuantityOptionsResponse,
    PeptideSpecies,
)
from app.services.dataset_reader import get_extension, read_dataframe
from app.services.peptide_metadata_store import (
    clear_peptide_metadata,
    get_peptide_metadata,
    save_peptide_metadata,
)
from app.services.peptide_tools import (
    _file_name_column,
    get_peptide_frame,
    peptide_overview,
    peptide_sequence_coverage,
)
from app.services.peptide_quantity import (
    default_peptide_quantity_column,
    peptide_quantity_columns,
)
from app.services.upload_limits import ensure_upload_size

LOGGER = logging.getLogger(__name__)


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
def get_peptide_overview() -> PeptideOverviewResponse:
    try:
        return PeptideOverviewResponse(**peptide_overview())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load peptide overview")
        raise HTTPException(status_code=500, detail="Failed to load peptide overview.") from e


@router.get("/quantity-options", response_model=PeptideQuantityOptionsResponse)
def get_peptide_quantity_options() -> PeptideQuantityOptionsResponse:
    try:
        frame = get_peptide_frame()
        columns = peptide_quantity_columns(frame)
        default_column = default_peptide_quantity_column(frame)
        return PeptideQuantityOptionsResponse(
            columns=columns,
            defaultColumn=default_column,
            requiresSelection=len(columns) > 1 and default_column is None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load peptide abundance options")
        raise HTTPException(status_code=500, detail="Failed to load peptide abundance options.") from e


@router.post("/metadata/upload", response_model=PeptideMetadataResponse)
def upload_peptide_metadata(file: UploadFile = File(...)) -> PeptideMetadataResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    try:
        ensure_upload_size(file, label="Peptide metadata file")
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e

    try:
        _ = get_extension(file.filename)
        frame = read_dataframe(file.filename, file.file)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to parse peptide metadata upload")
        raise HTTPException(status_code=400, detail="Failed to parse metadata file.") from e

    stored = save_peptide_metadata(file.filename, frame)
    return _metadata_response(stored)


@router.post("/metadata/generate", response_model=PeptideMetadataResponse)
def generate_peptide_metadata(
    payload: PeptideMetadataGenerateRequest,
) -> PeptideMetadataResponse:
    try:
        frame = get_peptide_frame()
        file_col = _file_name_column(frame)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load peptide samples")
        raise HTTPException(status_code=500, detail="Failed to load peptide samples.") from e

    sample_values = frame[file_col].dropna().astype(str).str.strip()
    samples = sample_values[sample_values != ""].drop_duplicates().tolist()
    available = set(samples)
    assigned: set[str] = set()
    rows: list[dict[str, str]] = []
    for condition in payload.conditions:
        condition_name = condition.name.strip()
        if not condition_name:
            continue
        for raw_sample in condition.columns:
            sample = str(raw_sample).strip()
            if sample not in available or sample in assigned:
                continue
            assigned.add(sample)
            rows.append({"sample": sample, "condition": condition_name})

    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Assign at least one peptide file name to a condition.",
        )

    metadata = pd.DataFrame(rows, columns=["sample", "condition"])
    stored = save_peptide_metadata("Peptide Annotation (Data > Annotation)", metadata)
    return _metadata_response(stored)


@router.get("/metadata/current", response_model=PeptideMetadataResponse)
def get_current_peptide_metadata() -> PeptideMetadataResponse:
    stored = get_peptide_metadata()
    if stored is None:
        raise HTTPException(status_code=404, detail="No peptide metadata is currently stored.")
    return _metadata_response(stored)


@router.delete("/metadata/current")
def clear_current_peptide_metadata() -> dict[str, object]:
    clear_peptide_metadata(active_package_only=True)
    return {"cleared": True}


@router.get("/sequence-coverage", response_model=PeptideCoverageResponse)
def get_sequence_coverage(
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
        LOGGER.exception("Failed to calculate sequence coverage")
        raise HTTPException(status_code=500, detail="Failed to calculate sequence coverage.") from e

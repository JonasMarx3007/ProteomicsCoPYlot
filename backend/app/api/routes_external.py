from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.schemas.external import PeptideCollapseRequest, PeptideCollapseResponse
from app.services.external_tools import run_peptide_collapse

router = APIRouter(prefix="/api/external", tags=["external"])


@router.post("/peptide-collapse/run", response_model=PeptideCollapseResponse)
async def run_peptide_collapse_route(payload: PeptideCollapseRequest) -> PeptideCollapseResponse:
    try:
        return run_peptide_collapse(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Peptide collapse failed: {e}") from e


@router.post("/peptide-collapse/upload")
async def upload_peptide_collapse_route(
    file: UploadFile = File(...),
    cutoff: float = Form(0.0),
    collapseVersion: Literal["newest", "legacy"] = Form("newest"),
) -> FileResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    if cutoff < 0 or cutoff > 1:
        raise HTTPException(status_code=400, detail="Localization cutoff must be between 0 and 1.")

    temp_dir = Path(tempfile.mkdtemp(prefix="copylot_peptide_collapse_"))
    safe_name = Path(file.filename).name
    input_path = temp_dir / f"{uuid4().hex}_{safe_name}"
    output_name = f"{Path(safe_name).stem or 'peptide'}_collapsed.tsv"
    output_path = temp_dir / output_name

    try:
        with input_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        result = run_peptide_collapse(
            PeptideCollapseRequest(
                inputPath=str(input_path),
                outputPath=str(output_path),
                cutoff=cutoff,
                collapseVersion=collapseVersion,
            )
        )
        if not result.success or not output_path.is_file():
            raise ValueError(result.error or "Peptide collapse did not complete successfully.")
        return FileResponse(
            path=str(output_path),
            filename=output_name,
            media_type="text/tab-separated-values",
            background=BackgroundTask(lambda: shutil.rmtree(temp_dir, ignore_errors=True)),
        )
    except ValueError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Peptide collapse failed: {e}") from e

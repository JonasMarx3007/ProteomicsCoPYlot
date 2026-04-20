from __future__ import annotations

import io
import os
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.restore import RestoreExportRequest, RestoreImportResponse, RestoreMissingFile
from app.services.restore_state import (
    RestoreStateError,
    apply_restore_state,
    decode_restore_blob,
    describe_restore_version_warning,
    export_state_blob,
    inspect_missing_files,
    parse_replacements_manifest,
)
from app.services.annotation_store import reset_all_annotations
from app.services.condition_palette_store import reset_condition_palettes
from app.services.dataset_store import reset_all_datasets
from app.services.metadata_upload_store import reset_all_uploaded_metadata
from app.services.peptide_metadata_store import clear_peptide_metadata

router = APIRouter(prefix="/api/restore", tags=["restore"])
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _reset_on_browser_load_enabled() -> bool:
    return str(os.getenv("COPYLOT_RESET_ON_BROWSER_LOAD", "")).strip().lower() in TRUTHY_VALUES


@router.post("/export")
async def export_restore_state(payload: RestoreExportRequest) -> StreamingResponse:
    try:
        blob = export_state_blob(ui_state=payload.uiState)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to export restore state: {exc}") from exc

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"copylot_state_{timestamp}.copylotstate"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=RestoreImportResponse)
async def import_restore_state(
    stateFile: UploadFile = File(...),
    replacementsManifest: str | None = Form(default=None),
    replacements: list[UploadFile] = File(default=[]),
) -> RestoreImportResponse:
    try:
        blob = await stateFile.read()
        state = decode_restore_blob(blob)
        replacement_map = parse_replacements_manifest(replacementsManifest, replacements)
        missing = inspect_missing_files(state, replacement_map)
        version_warning = describe_restore_version_warning(state)
    except RestoreStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse restore state: {exc}") from exc

    ui_state = state.get("uiState")
    if missing:
        payload = RestoreImportResponse(
            ok=False,
            uiState=ui_state if isinstance(ui_state, dict) else {},
            warnings=[version_warning] if version_warning else [],
            missingFiles=[
                RestoreMissingFile(
                    packageName=item.package_name,
                    kind=item.kind,
                    filename=item.filename,
                    expectedPath=item.expected_path,
                    message=item.message,
                )
                for item in missing
            ],
            restoredDatasets=[],
            restoredAnnotations=[],
        )
        return JSONResponse(status_code=409, content=payload.model_dump())

    try:
        restored = apply_restore_state(state, replacement_map)
    except RestoreStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to apply restore state: {exc}") from exc

    return RestoreImportResponse(
        ok=True,
        uiState=ui_state if isinstance(ui_state, dict) else {},
        warnings=([version_warning] if version_warning else []) + restored.warnings,
        missingFiles=[],
        restoredDatasets=restored.restored_datasets,
        restoredAnnotations=restored.restored_annotations,
    )


@router.post("/browser-session-reset")
async def browser_session_reset() -> dict[str, bool]:
    enabled = _reset_on_browser_load_enabled()
    if enabled:
        reset_all_annotations()
        reset_all_uploaded_metadata()
        reset_all_datasets()
        reset_condition_palettes()
        clear_peptide_metadata()
    return {"ok": True, "enabled": enabled}


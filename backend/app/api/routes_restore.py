from __future__ import annotations

import io
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

router = APIRouter(prefix="/api/restore", tags=["restore"])


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


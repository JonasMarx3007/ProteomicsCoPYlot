from __future__ import annotations

import logging

import io
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.restore import RestoreExportRequest, RestoreImportResponse, RestoreMissingFile
from app.services.restore_state import (
    RESTORE_COMPATIBILITY_NOTICE,
    RestoreStateError,
    apply_restore_state,
    decode_restore_blob,
    describe_restore_version_warning,
    export_state_blob,
    inspect_missing_files,
    parse_replacements_manifest,
    restore_upload_max_bytes,
)
from app.services.annotation_store import reset_all_annotations
from app.services.request_security import local_path_access_allowed
from app.services.condition_palette_store import reset_condition_palettes
from app.services.phospho_localization import reset_localization_cutoff
from app.services.dataset_store import reset_all_datasets
from app.services.metadata_upload_store import reset_all_uploaded_metadata
from app.services.peptide_metadata_store import clear_peptide_metadata
from app.services.viewer_portal import (
    ensure_viewer_session_bootstrapped,
    viewer_portal_enabled,
    viewer_session_authenticated,
)
from app.services.viewer_bootstrap import bootstrap_current_viewer_session, viewer_mode_enabled
from app.services.env_settings import env_flag
from app.api.download_headers import attachment_disposition

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/restore", tags=["restore"])


def _reset_on_browser_load_enabled() -> bool:
    if viewer_mode_enabled():
        return False
    return env_flag("COPYLOT_RESET_ON_BROWSER_LOAD", True)


@router.post("/export")
def export_restore_state(payload: RestoreExportRequest) -> StreamingResponse:
    try:
        blob = export_state_blob(ui_state=payload.uiState, portable=payload.portable)
    except RestoreStateError as exc:
        LOGGER.exception("Save-state export rejected")
        raise HTTPException(
            status_code=400,
            detail=("Save state cannot be exported. Ask the administrator to check the restore "
                    "size limits and server log for details. Your current analysis is unchanged."),
        ) from exc
    except Exception as exc:
        LOGGER.exception("Failed to export restore state")
        raise HTTPException(status_code=500, detail="Failed to export restore state.") from exc

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = "portable_state" if payload.portable else "state"
    filename = f"copylot_{label}_{timestamp}.copylotstate"
    return StreamingResponse(
        io.BytesIO(blob),
        media_type="application/octet-stream",
        headers={"Content-Disposition": attachment_disposition(filename)},
    )


@router.post("/import", response_model=RestoreImportResponse)
async def import_restore_state(
    request: Request,
    stateFile: UploadFile = File(...),
    replacementsManifest: str | None = Form(default=None),
    replacements: list[UploadFile] = File(default=[]),
) -> RestoreImportResponse:
    allow_local_paths = local_path_access_allowed(request)
    try:
        upload_limit = restore_upload_max_bytes()
        blob = await stateFile.read(upload_limit + 1)
        if len(blob) > upload_limit:
            raise RestoreStateError("Restore file exceeds the configured upload limit.")
        state = await run_in_threadpool(decode_restore_blob, blob)
        replacement_map = await run_in_threadpool(
            parse_replacements_manifest,
            replacementsManifest,
            replacements,
        )
        missing = await run_in_threadpool(
            inspect_missing_files, state, replacement_map, allow_local_paths=allow_local_paths,
        )
        version_warning = describe_restore_version_warning(state)
    except RestoreStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to parse restore state")
        raise HTTPException(status_code=400, detail="Failed to parse restore state.") from exc

    ui_state = state.get("uiState")
    if missing:
        payload = RestoreImportResponse(
            ok=False,
            uiState=ui_state if isinstance(ui_state, dict) else {},
            warnings=[
                RESTORE_COMPATIBILITY_NOTICE,
                *([version_warning] if version_warning else []),
            ],
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
        restored = await run_in_threadpool(
            apply_restore_state, state, replacement_map, allow_local_paths=allow_local_paths,
        )
    except RestoreStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Failed to apply restore state")
        raise HTTPException(status_code=500, detail="Failed to apply restore state.") from exc

    return RestoreImportResponse(
        ok=True,
        uiState=ui_state if isinstance(ui_state, dict) else {},
        warnings=[
            RESTORE_COMPATIBILITY_NOTICE,
            *([version_warning] if version_warning else []),
            *restored.warnings,
        ],
        missingFiles=[],
        restoredDatasets=restored.restored_datasets,
        restoredAnnotations=restored.restored_annotations,
    )


@router.post("/browser-session-reset")
def browser_session_reset() -> dict[str, bool]:
    enabled = _reset_on_browser_load_enabled()
    if enabled:
        from app.services.notebook_snapshots import forget_session
        from app.services.session_context import get_session_id
        forget_session(get_session_id())
        reset_all_annotations()
        reset_all_uploaded_metadata()
        reset_all_datasets()
        reset_condition_palettes()
        reset_localization_cutoff()
        clear_peptide_metadata()
        if viewer_portal_enabled() and viewer_session_authenticated():
            try:
                ensure_viewer_session_bootstrapped(force_reload=True)
            except Exception:
                # Keep endpoint resilient; frontend handles follow-up auth/status checks.
                pass
        elif viewer_mode_enabled():
            try:
                bootstrap_current_viewer_session(force_reload=True)
            except Exception:
                # Keep endpoint resilient; frontend handles follow-up retries.
                pass
    return {"ok": True, "enabled": enabled}


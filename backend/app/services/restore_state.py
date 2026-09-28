from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Literal, Mapping, get_args
from uuid import uuid4

import pandas as pd
from fastapi import UploadFile

from app.app_version import APP_VERSION
from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationImputationInfo,
    NormalizationMethod,
    phosprot_filter_config,
)
from app.services.managed_temp import open_private, private_temp_dir, write_private_bytes
from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.annotation_store import (
    get_annotation,
    list_annotation_profiles,
    reset_all_annotations,
    restore_annotation_session_state,
    save_annotation,
    snapshot_annotation_session_state,
)
from app.services.condition_palette_store import (
    get_condition_palette,
    reset_condition_palettes,
    restore_condition_palette_session_state,
    set_condition_palette,
    snapshot_condition_palette_session_state,
)
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import (
    create_package,
    get_active_package,
    get_all_current_datasets,
    get_current_dataset,
    list_packages,
    reset_all_datasets,
    restore_dataset_session_state,
    save_peptide_path,
    save_table_dataset,
    set_active_package,
    snapshot_dataset_session_state,
)
from app.services.metadata_upload_store import (
    DEFAULT_METADATA_PROFILE_NAME,
    create_profile as create_metadata_profile,
    get_active_profile,
    get_uploaded_metadata,
    list_profiles,
    reset_all_uploaded_metadata,
    restore_metadata_session_state,
    save_uploaded_metadata,
    set_active_profile,
    snapshot_metadata_session_state,
)
from app.services.peptide_metadata_store import (
    clear_peptide_metadata,
    get_peptide_metadata,
    restore_peptide_metadata_session_state,
    save_peptide_metadata,
    snapshot_peptide_metadata_session_state,
)
from app.services.session_context import get_session_id
from app.services.upload_limits import upload_max_bytes, upload_size_bytes

TableKind = Literal["protein", "phospho", "phosprot"]
DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
_TABLE_KINDS: tuple[TableKind, ...] = ("protein", "phospho", "phosprot")
_DATASET_KINDS: tuple[DatasetKind, ...] = ("protein", "phospho", "phosprot", "peptide")
_METADATA_KINDS: tuple[Literal["protein", "phospho"], ...] = ("protein", "phospho")
_STATE_FORMAT = "copylot_state_v1"
_DEFAULT_RESTORE_UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024
_DEFAULT_RESTORE_EXPANDED_LIMIT_BYTES = 256 * 1024 * 1024
_DEFAULT_RESTORE_TABLE_MAX_ROWS = 5_000_000
_DEFAULT_RESTORE_TABLE_MAX_COLUMNS = 50_000
_DEFAULT_RESTORE_TABLE_MAX_CELLS = 50_000_000
_DEFAULT_RESTORE_REPLACEMENT_MAX_FILES = 256
_DEFAULT_RESTORE_MANIFEST_MAX_CHARS = 1_000_000
_READ_CHUNK_BYTES = 1024 * 1024
LOGGER = logging.getLogger(__name__)
RESTORE_COMPATIBILITY_NOTICE = (
    "Save states are compatibility snapshots: saved settings were restored, and any "
    "options not present in the file use the current application defaults."
)
_RESTORE_LOCKS_GUARD = RLock()
_RESTORE_LOCKS: dict[str, RLock] = {}


class RestoreStateError(ValueError):
    pass


def _current_restore_lock() -> RLock:
    session_id = get_session_id()
    with _RESTORE_LOCKS_GUARD:
        lock = _RESTORE_LOCKS.get(session_id)
        if lock is None:
            lock = RLock()
            _RESTORE_LOCKS[session_id] = lock
        return lock


def _positive_env_bytes(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return max(1, parsed)


def restore_upload_max_bytes() -> int:
    return _positive_env_bytes(
        "COPYLOT_RESTORE_UPLOAD_MAX_BYTES",
        _DEFAULT_RESTORE_UPLOAD_LIMIT_BYTES,
    )


def restore_expanded_max_bytes() -> int:
    return _positive_env_bytes(
        "COPYLOT_RESTORE_EXPANDED_MAX_BYTES",
        _DEFAULT_RESTORE_EXPANDED_LIMIT_BYTES,
    )


def restore_replacement_max_bytes() -> int:
    return _positive_env_bytes("COPYLOT_RESTORE_REPLACEMENT_MAX_BYTES", upload_max_bytes())


def restore_replacements_total_max_bytes() -> int:
    per_file = restore_replacement_max_bytes()
    return _positive_env_bytes("COPYLOT_RESTORE_REPLACEMENTS_TOTAL_MAX_BYTES", per_file * 2)


def restore_table_max_rows() -> int:
    return _positive_env_bytes("COPYLOT_RESTORE_TABLE_MAX_ROWS", _DEFAULT_RESTORE_TABLE_MAX_ROWS)


def restore_table_max_columns() -> int:
    return _positive_env_bytes("COPYLOT_RESTORE_TABLE_MAX_COLUMNS", _DEFAULT_RESTORE_TABLE_MAX_COLUMNS)


def restore_table_max_cells() -> int:
    return _positive_env_bytes("COPYLOT_RESTORE_TABLE_MAX_CELLS", _DEFAULT_RESTORE_TABLE_MAX_CELLS)


def restore_replacement_max_files() -> int:
    return _positive_env_bytes(
        "COPYLOT_RESTORE_REPLACEMENT_MAX_FILES",
        _DEFAULT_RESTORE_REPLACEMENT_MAX_FILES,
    )


def restore_manifest_max_chars() -> int:
    return _positive_env_bytes(
        "COPYLOT_RESTORE_MANIFEST_MAX_CHARS",
        _DEFAULT_RESTORE_MANIFEST_MAX_CHARS,
    )


@dataclass
class MissingStateFile:
    package_name: str
    kind: DatasetKind
    filename: str | None
    expected_path: str | None
    message: str


@dataclass
class PreparedRestoreInput:
    frame_by_package_kind: dict[tuple[str, TableKind], tuple[pd.DataFrame, str, str | None]]
    peptide_path_by_package: dict[str, tuple[str, str | None]]
    warnings: list[str]
    changed_datasets: set[tuple[str, TableKind]]


@dataclass
class ReplacementInput:
    file: UploadFile
    source_path: str | None = None
    size_bytes: int | None = None


@dataclass
class RestoreApplyResult:
    warnings: list[str]
    restored_datasets: list[str]
    restored_annotations: list[str]


@dataclass
class DeferredAutoMetadataRestore:
    package_name: str
    profile_name: str
    metadata_kind: Literal["protein", "phospho"]
    filename: str
    frame_payload: Any


def _frame_to_payload(frame: pd.DataFrame) -> dict[str, Any]:
    safe = frame.copy().where(pd.notna(frame), None)
    return {
        "columns": [str(column) for column in safe.columns],
        "data": safe.values.tolist(),
    }


def _frame_from_payload(payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise RestoreStateError("Invalid table payload in restore state.")
    columns_raw = payload.get("columns")
    data_raw = payload.get("data")
    if not isinstance(columns_raw, list) or not isinstance(data_raw, list):
        raise RestoreStateError("Invalid table payload format in restore state.")
    row_count = len(data_raw)
    column_count = len(columns_raw)
    if row_count > restore_table_max_rows():
        raise RestoreStateError("Restore table exceeds the configured row limit.")
    if column_count > restore_table_max_columns():
        raise RestoreStateError("Restore table exceeds the configured column limit.")
    if row_count * column_count > restore_table_max_cells():
        raise RestoreStateError("Restore table exceeds the configured cell limit.")
    for row in data_raw:
        if not isinstance(row, list) or len(row) != column_count:
            raise RestoreStateError("Restore table rows do not match the declared columns.")
    columns = [str(column) for column in columns_raw]
    return pd.DataFrame(data_raw, columns=columns)


def _read_table_from_path(path_text: str) -> pd.DataFrame:
    path = Path(path_text).expanduser()
    with path.open("rb") as handle:
        return read_dataframe(path.name, handle)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"none", "null"}:
        return None
    return text


def _normalize_dataset_kind(value: Any) -> DatasetKind | None:
    text = str(value or "").strip().lower()
    if text in _DATASET_KINDS:
        return text  # type: ignore[return-value]
    return None


def _normalize_table_kind(value: Any) -> TableKind | None:
    text = str(value or "").strip().lower()
    if text in _TABLE_KINDS:
        return text  # type: ignore[return-value]
    return None


def _coerce_filter_config(
    payload: Any, warnings: list[str] | None = None, label: str = ""
) -> AnnotationFilterConfig:
    """Rebuild a saved filter configuration, reporting anything not recognised.

    A state file is user-supplied, so refusing to load one is worse than loading
    it approximately -- but a value that has to be coerced changes the analysis.
    Silently rewriting an unknown normalization to "none" re-runs everything
    unnormalized and the methods report then states "none", which is how a
    reproducibility claim quietly becomes false. A field that is simply absent is
    a legacy state file and defaults without comment; only a present-but-
    unrecognised value is reported.
    """
    def report(message: str) -> None:
        if warnings is not None:
            warnings.append(f"{label}{message}" if label else message)

    if not isinstance(payload, dict):
        return AnnotationFilterConfig()
    method_raw = str(payload.get("method", "at_least_n")).strip()
    min_present_raw = payload.get("minPresent", 0)
    min_percentage_raw = payload.get("minPercentage", 70.0)
    mode_raw = str(payload.get("mode", "per_group")).strip()
    min_present = int(min_present_raw) if isinstance(min_present_raw, (int, float)) else 0
    min_percentage = (
        float(min_percentage_raw)
        if isinstance(min_percentage_raw, (int, float))
        else 70.0
    )
    if min_present < 0:
        report(f"Saved minimum present count {min_present} is negative; restored as 0.")
        min_present = 0
    if not 0.0 <= min_percentage <= 100.0:
        clamped = min(100.0, max(0.0, min_percentage))
        report(
            f"Saved minimum percentage {min_percentage} is outside 0-100; "
            f"restored as {clamped}."
        )
        min_percentage = clamped
    if method_raw not in {"at_least_n", "percentage"}:
        if "method" in payload:
            report(f"Saved filter method {method_raw!r} is not recognised; restored as 'at_least_n'.")
        method_raw = "at_least_n"
    if mode_raw not in {"per_group", "in_at_least_one_group", "overall"}:
        if "mode" in payload:
            report(f"Saved filter mode {mode_raw!r} is not recognised; restored as 'per_group'.")
        mode_raw = "per_group"
    # The allowed set comes from the schema so it cannot drift from the app, but
    # that does not stop a value this build has never heard of from being coerced:
    # an unrecognised method is rewritten to "none" and the analysis re-runs
    # unnormalized, so say so.
    normalization_raw = str(payload.get("normalization", "none")).strip().lower()
    if normalization_raw not in set(get_args(NormalizationMethod)):
        if "normalization" in payload:
            report(
                f"Saved normalization {normalization_raw!r} is not recognised; restored "
                "as 'none', so the analysis was re-run without normalization."
            )
        normalization_raw = "none"
    return AnnotationFilterConfig(
        method=method_raw,
        minPresent=min_present,
        minPercentage=min_percentage,
        mode=mode_raw,
        normalization=normalization_raw,
    )  # type: ignore[arg-type]


def _coerce_phosprot_aggregation(payload: Any) -> str | None:
    """Accept only a known aggregation mode from a restored state file.

    A state file is user-supplied, so an unrecognised value is dropped rather
    than trusted: `None` means "unknown provenance", which is the safe reading.
    """
    from app.schemas.annotation import PhosprotAggregationMode

    text = str(payload or "").strip().lower()
    allowed = {*get_args(PhosprotAggregationMode), "uploaded"}
    return text if text in allowed else None


def _coerce_imputation(payload: Any) -> tuple[AnnotationImputationInfo | None, str | None]:
    """The saved imputation record, or why it could not be read.

    `(None, None)` means no record was saved. `(None, reason)` means a record
    was saved but does not validate -- an older schema, a renamed field. The
    caller decides what to do with the imputed matrix in that case; it must
    not be thrown away in silence.
    """
    if payload is None:
        return None, None
    if not isinstance(payload, dict):
        return None, f"expected an object, got {type(payload).__name__}"
    try:
        return AnnotationImputationInfo(**payload), None
    except Exception as exc:
        return None, str(exc).splitlines()[0][:200]


def _table_fingerprint(frame: pd.DataFrame) -> str:
    """Identify the loaded values, independent of integer/float column inference."""
    content = frame.to_csv(index=False, float_format="%.17g", lineterminator="\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any] | None:
    """Size and SHA-256 of a dataset file, so a restore can tell it was replaced."""
    try:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        return None
    return {"sizeBytes": size, "sha256": digest.hexdigest()}


def _fingerprint_mismatch(entry: Mapping[str, Any], path: Path) -> str | None:
    """Why the file at `path` is not the one the state was saved from, or None.

    Old exports carry no fingerprint; those are not checked.
    """
    return _compare_fingerprint(entry, _file_fingerprint(path))


def _compare_fingerprint(entry: Mapping[str, Any], current: dict[str, Any] | None) -> str | None:
    saved_size = entry.get("sizeBytes")
    saved_hash = _optional_text(entry.get("sha256"))
    if saved_size is None and saved_hash is None:
        return None
    if saved_size is not None and (type(saved_size) is not int or saved_size < 0):
        return "saved file size is invalid; file identity could not be verified"
    if current is None:
        return "file fingerprint could not be read; file identity could not be verified"
    if saved_size is not None and saved_size != current["sizeBytes"]:
        return f"size {current['sizeBytes']:,} bytes now, {saved_size:,} when saved"
    if saved_hash is not None and saved_hash.lower() != current["sha256"]:
        return "contents differ (SHA-256 mismatch)"
    return None


def _normalize_metadata_source(payload: Any) -> Literal["manual", "auto", "uploaded", "shared_phospho"]:
    text = str(payload or "").strip().lower()
    if text in {"manual", "auto", "uploaded", "shared_phospho"}:
        return text  # type: ignore[return-value]
    return "manual"


def _restore_upload_dir() -> Path:
    return private_temp_dir("restore_uploads")


def _table_backup_dir() -> Path:
    """Where a non-portable export writes a copy of a table that has no file.

    Its own directory, apart from `table_uploads`: an uploaded file lands there
    too when the client sent no path, and the two must stay distinguishable --
    a derived table is embedded in the export, an upload is not.
    """
    return private_temp_dir("table_derived")


def _is_derived_table(stored: Any) -> bool:
    """Whether a stored table was computed in the tool rather than uploaded.

    A derived table has no source file; the only path it can ever carry is the
    temp copy `_ensure_exportable_table_path` writes for a non-portable export,
    which lives under the table backup directory.
    """
    source_path = _optional_text(getattr(stored, "source_path", None))
    if not source_path:
        return True
    try:
        return Path(source_path).expanduser().resolve().parent == _table_backup_dir().resolve()
    except OSError:
        return False


def _ensure_exportable_table_path(stored: Any) -> str | None:
    existing_path = _optional_text(getattr(stored, "source_path", None))
    if existing_path:
        return existing_path

    frame = getattr(stored, "frame", None)
    if not isinstance(frame, pd.DataFrame):
        return None

    filename = Path(str(getattr(stored, "filename", "") or "dataset")).stem or "dataset"
    target = _table_backup_dir() / f"{uuid4().hex}_{filename}.tsv"
    try:
        with open_private(target, "w") as handle:
            frame.to_csv(handle, sep="\t", index=False)
    except Exception:
        return None

    resolved = str(target.resolve())
    try:
        setattr(stored, "source_path", resolved)
    except Exception:
        pass
    return resolved


def _parse_state_blob(blob: bytes) -> dict[str, Any]:
    if not blob:
        raise RestoreStateError("Restore file is empty.")
    if len(blob) > restore_upload_max_bytes():
        raise RestoreStateError("Restore file exceeds the configured upload limit.")
    raw: bytes
    if blob.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as handle:
                raw = handle.read(restore_expanded_max_bytes() + 1)
        except Exception as exc:
            raise RestoreStateError(f"Restore file has invalid gzip data: {exc}") from exc
    else:
        raw = blob
    if len(raw) > restore_expanded_max_bytes():
        raise RestoreStateError("Expanded restore state exceeds the configured size limit.")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RestoreStateError(f"Restore file is invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RestoreStateError("Restore file must contain a JSON object.")
    state_format = str(parsed.get("format", "")).strip()
    if state_format != _STATE_FORMAT:
        raise RestoreStateError(
            f"Unsupported restore format '{state_format or 'unknown'}'. Expected '{_STATE_FORMAT}'."
        )
    return parsed


def describe_restore_version_warning(state: dict[str, Any]) -> str | None:
    saved_version = _optional_text(state.get("appVersion"))
    if not saved_version or saved_version == APP_VERSION:
        return None
    return (
        f"Save state was created with app version {saved_version}. "
        f"Current app version is {APP_VERSION}."
    )


def _serialize_state_payload(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def _export_profile_names(package_name: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for profile_name in list_profiles(package_name=package_name):
        normalized = str(profile_name).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    for profile_name in list_annotation_profiles(package_name=package_name):
        normalized = str(profile_name).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    if DEFAULT_METADATA_PROFILE_NAME not in seen:
        default_has_annotation = any(
            get_annotation(
                kind,
                package_name=package_name,
                metadata_profile_name=DEFAULT_METADATA_PROFILE_NAME,
            )
            is not None
            for kind in _TABLE_KINDS
        )
        if default_has_annotation:
            ordered.append(DEFAULT_METADATA_PROFILE_NAME)
    return ordered


def export_state_blob(
    *,
    ui_state: dict[str, Any] | None = None,
    portable: bool = False,
) -> bytes:
    active_package = get_active_package()
    packages_payload: list[dict[str, Any]] = []

    for package_name in list_packages(include_empty=True):
        current = get_all_current_datasets(package_name=package_name)
        dataset_payload: dict[str, Any] = {}
        for kind in _TABLE_KINDS:
            stored = current.get(kind)
            if stored is None:
                dataset_payload[kind] = None
                continue
            derived = _is_derived_table(stored)
            entry: dict[str, Any] = {
                "filename": str(getattr(stored, "filename", "") or ""),
                "path": None if portable else _ensure_exportable_table_path(stored),
                "phosprotAggregation": getattr(stored, "phosprot_aggregation", None),
            }
            fingerprint_path = entry["path"] or _optional_text(getattr(stored, "source_path", None))
            if fingerprint_path:
                # So a restore can tell when the file at this path has been
                # overwritten since (a re-exported search under the same name).
                fingerprint = _file_fingerprint(Path(str(fingerprint_path)).expanduser())
                if fingerprint is not None:
                    entry.update(fingerprint)
            frame = getattr(stored, "frame", None)
            if isinstance(frame, pd.DataFrame):
                entry["tableSha256"] = _table_fingerprint(frame)
            if derived and isinstance(frame, pd.DataFrame):
                # A table derived inside the tool (a phosprot aggregation) has no
                # file of its own. The temp copy written above is a convenience
                # on this machine; the table itself travels in the export, so a
                # portable restore never asks for a file the user never had.
                entry["derived"] = True
                entry["frame"] = _frame_to_payload(frame)
            dataset_payload[kind] = entry
        peptide_stored = current.get("peptide")
        dataset_payload["peptide"] = (
            None
            if peptide_stored is None
            else {
                "filename": str(getattr(peptide_stored, "filename", "") or ""),
                "path": (
                    None
                    if portable
                    else _optional_text(getattr(peptide_stored, "path", None))
                ),
            }
        )

        profiles = _export_profile_names(package_name)
        metadata_profiles_payload: list[dict[str, Any]] = []
        for profile_name in profiles:
            profile_payload: dict[str, Any] = {"name": profile_name}
            for kind in _METADATA_KINDS:
                stored_metadata = get_uploaded_metadata(
                    kind,
                    package_name=package_name,
                    profile_name=profile_name,
                )
                if stored_metadata is None:
                    profile_payload[kind] = None
                    continue
                profile_payload[kind] = {
                    "filename": stored_metadata.filename,
                    "frame": _frame_to_payload(stored_metadata.frame),
                    "autoGenerated": bool(stored_metadata.auto_generated),
                    "sourceProfiles": (
                        list(stored_metadata.source_profiles)
                        if stored_metadata.source_profiles is not None
                        else None
                    ),
                }
            metadata_profiles_payload.append(profile_payload)

        annotation_payload: list[dict[str, Any]] = []
        for profile_name in profiles:
            for kind in _TABLE_KINDS:
                stored_annotation = get_annotation(
                    kind,
                    package_name=package_name,
                    metadata_profile_name=profile_name,
                )
                if stored_annotation is None:
                    continue
                annotation_payload.append(
                    {
                        "profile": profile_name,
                        "kind": kind,
                        "isLog2Transformed": bool(stored_annotation.is_log2_transformed),
                        "log2AutoDetected": bool(
                            getattr(stored_annotation, "log2_auto_detected", False)
                        ),
                        "metadataSource": str(getattr(stored_annotation, "metadata_source", "manual")),
                        "filter": {
                            "method": str(stored_annotation.filter_config.method),
                            "minPresent": int(stored_annotation.filter_config.minPresent),
                            "minPercentage": float(stored_annotation.filter_config.minPercentage),
                            "mode": str(stored_annotation.filter_config.mode),
                            "normalization": str(stored_annotation.filter_config.normalization),
                        },
                        "imputation": (
                            stored_annotation.imputation.model_dump()
                            if stored_annotation.imputation is not None
                            else None
                        ),
                        # Which aggregation produced a phosprot frame. Without it a
                        # restored session forgets that `robust_site_median` values
                        # are ratios rather than abundances, and the abundance plot
                        # goes back to labelling them "Intensity".
                        "phosprotAggregation": getattr(
                            stored_annotation, "phosprot_aggregation", None
                        ),
                        "imputedFrame": (
                            _frame_to_payload(stored_annotation.imputed_data)
                            if isinstance(
                                getattr(stored_annotation, "imputed_data", None),
                                pd.DataFrame,
                            )
                            and not stored_annotation.imputed_data.empty
                            else None
                        ),
                        "metadataFrame": _frame_to_payload(stored_annotation.metadata),
                    }
                )

        package_peptide_metadata = get_peptide_metadata(package_name=package_name)
        packages_payload.append(
            {
                "name": package_name,
                "datasets": dataset_payload,
                "metadata": {
                    "activeProfile": get_active_profile(package_name=package_name),
                    "profiles": metadata_profiles_payload,
                },
                "annotations": annotation_payload,
                "peptideMetadata": (
                    None
                    if package_peptide_metadata is None
                    else {
                        "filename": package_peptide_metadata.filename,
                        "frame": _frame_to_payload(package_peptide_metadata.frame),
                    }
                ),
            }
        )

    payload: dict[str, Any] = {
        "format": _STATE_FORMAT,
        "appVersion": APP_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "portable": portable,
        "uiState": ui_state or {},
        "backend": {
            "activePackage": active_package,
            "packages": packages_payload,
            "conditionPalettes": {
                "protein": get_condition_palette("protein"),
                "phospho": get_condition_palette("phospho"),
                "phosprot": get_condition_palette("phosprot"),
            },
        },
    }
    return _serialize_state_payload(payload)


def parse_replacements_manifest(
    manifest_text: str | None,
    replacement_files: Iterable[UploadFile] | None,
) -> dict[tuple[str, DatasetKind], ReplacementInput]:
    files = list(replacement_files or [])
    if not files:
        return {}
    if len(files) > restore_replacement_max_files():
        raise RestoreStateError("Too many replacement files were provided.")
    if not manifest_text:
        raise RestoreStateError("Replacement file manifest is required when replacement files are provided.")
    if len(manifest_text) > restore_manifest_max_chars():
        raise RestoreStateError("Replacement manifest exceeds the configured size limit.")
    try:
        parsed = json.loads(manifest_text)
    except Exception as exc:
        raise RestoreStateError(f"Replacement manifest is invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise RestoreStateError("Replacement manifest must be a JSON array.")
    if len(parsed) != len(files):
        raise RestoreStateError("Replacement manifest size does not match number of replacement files.")

    mapped: dict[tuple[str, DatasetKind], ReplacementInput] = {}
    total_size = 0
    per_file_limit = restore_replacement_max_bytes()
    total_limit = restore_replacements_total_max_bytes()
    for index, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise RestoreStateError("Replacement manifest entries must be objects.")
        package_name = str(entry.get("packageName", "")).strip()
        kind = _normalize_dataset_kind(entry.get("kind"))
        source_path = _optional_text(entry.get("sourcePath"))
        if not package_name or kind is None:
            raise RestoreStateError("Replacement manifest entry is missing packageName or kind.")
        key = (package_name, kind)
        if key in mapped:
            raise RestoreStateError(f"Replacement manifest contains duplicate entry for {package_name}:{kind}.")
        try:
            size_bytes = upload_size_bytes(
                files[index],
                label=f"Replacement file for {package_name}:{kind}",
                max_bytes=per_file_limit,
            )
        except ValueError as exc:
            raise RestoreStateError(str(exc)) from exc
        total_size += size_bytes
        if total_size > total_limit:
            raise RestoreStateError("Replacement files exceed the configured aggregate upload limit.")
        mapped[key] = ReplacementInput(
            file=files[index],
            source_path=source_path,
            size_bytes=size_bytes,
        )
    return mapped


def _validate_replacement_inputs(
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
) -> None:
    total_size = 0
    per_file_limit = restore_replacement_max_bytes()
    total_limit = restore_replacements_total_max_bytes()
    for (package_name, kind), replacement in replacements.items():
        if isinstance(replacement.size_bytes, int):
            size_bytes = replacement.size_bytes
            if size_bytes > per_file_limit:
                raise RestoreStateError(
                    f"Replacement file for {package_name}:{kind} exceeds the configured upload limit."
                )
        else:
            try:
                size_bytes = upload_size_bytes(
                    replacement.file,
                    label=f"Replacement file for {package_name}:{kind}",
                    max_bytes=per_file_limit,
                )
            except ValueError as exc:
                raise RestoreStateError(str(exc)) from exc
        replacement.size_bytes = size_bytes
        total_size += size_bytes
        if total_size > total_limit:
            raise RestoreStateError("Replacement files exceed the configured aggregate upload limit.")


def _read_replacement_bytes(replacement: ReplacementInput, *, label: str) -> bytes:
    limit = restore_replacement_max_bytes()
    stream = getattr(replacement.file, "file", None)
    if stream is None or not hasattr(stream, "read"):
        raise RestoreStateError(f"{label} could not be read safely.")
    try:
        stream.seek(0)
    except Exception:
        pass
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = stream.read(min(_READ_CHUNK_BYTES, limit - observed + 1))
        if not chunk:
            break
        observed += len(chunk)
        if observed > limit:
            raise RestoreStateError(f"{label} exceeds the configured upload limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def inspect_missing_files(
    state: dict[str, Any],
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
    *, allow_local_paths: bool = True,
) -> list[MissingStateFile]:
    backend = state.get("backend")
    if not isinstance(backend, dict):
        raise RestoreStateError("Restore file is missing backend state.")
    packages = backend.get("packages")
    if not isinstance(packages, list):
        raise RestoreStateError("Restore file is missing package list.")

    missing: list[MissingStateFile] = []
    for package_entry in packages:
        if not isinstance(package_entry, dict):
            continue
        package_name = str(package_entry.get("name", "")).strip()
        if not package_name:
            continue
        datasets = package_entry.get("datasets")
        if not isinstance(datasets, dict):
            continue
        for kind in _DATASET_KINDS:
            dataset_entry = datasets.get(kind)
            if dataset_entry is None:
                continue
            if not isinstance(dataset_entry, dict):
                missing.append(
                    MissingStateFile(
                        package_name=package_name,
                        kind=kind,
                        filename=None,
                        expected_path=None,
                        message=f"Saved dataset definition for {kind} in package '{package_name}' is invalid.",
                    )
                )
                continue

            filename = _optional_text(dataset_entry.get("filename"))
            if dataset_entry.get("frame") is not None:
                # The table itself is in the export (a derived phosprot table).
                continue
            path_text = _optional_text(dataset_entry.get("path")) if allow_local_paths else None
            has_replacement = (package_name, kind) in replacements
            if path_text and not has_replacement:
                candidate = Path(path_text).expanduser()
                if candidate.exists() and candidate.is_file():
                    continue
                if has_replacement:
                    continue
                missing.append(
                    MissingStateFile(
                        package_name=package_name,
                        kind=kind,
                        filename=filename,
                        expected_path=path_text,
                        message=(
                            f"Saved path for {kind} dataset in package '{package_name}' does not exist."
                        ),
                    )
                )
                continue
            if has_replacement:
                continue
            missing.append(
                MissingStateFile(
                    package_name=package_name,
                    kind=kind,
                    filename=filename,
                    expected_path=None,
                    message=(
                        f"No saved absolute path was available for {kind} dataset in package '{package_name}'. "
                        "Upload a replacement file to continue restore."
                    ),
                )
            )
    return missing


def _prepare_restore_inputs(
    state: dict[str, Any],
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
    *, allow_local_paths: bool = True,
) -> PreparedRestoreInput:
    _validate_replacement_inputs(replacements)
    backend = state.get("backend")
    if not isinstance(backend, dict):
        raise RestoreStateError("Restore file is missing backend state.")
    packages = backend.get("packages")
    if not isinstance(packages, list):
        raise RestoreStateError("Restore file is missing package list.")

    frame_by_package_kind: dict[tuple[str, TableKind], tuple[pd.DataFrame, str, str | None]] = {}
    peptide_path_by_package: dict[str, tuple[str, str | None]] = {}
    changed_datasets: set[tuple[str, TableKind]] = set()
    warnings: list[str] = []

    for package_entry in packages:
        if not isinstance(package_entry, dict):
            continue
        package_name = str(package_entry.get("name", "")).strip()
        if not package_name:
            continue
        datasets = package_entry.get("datasets")
        if not isinstance(datasets, dict):
            continue
        for kind in _TABLE_KINDS:
            dataset_entry = datasets.get(kind)
            if dataset_entry is None:
                continue
            if not isinstance(dataset_entry, dict):
                raise RestoreStateError(
                    f"Saved dataset entry for {package_name}:{kind} is invalid."
                )
            filename = _optional_text(dataset_entry.get("filename")) or f"{kind}.csv"
            path_text = _optional_text(dataset_entry.get("path")) if allow_local_paths else None
            replacement = replacements.get((package_name, kind))
            embedded = dataset_entry.get("frame")
            if embedded is not None and replacement is None:
                try:
                    frame_by_package_kind[(package_name, kind)] = (
                        _frame_from_payload(embedded),
                        filename,
                        None,
                    )
                    continue
                except RestoreStateError as exc:
                    raise RestoreStateError(
                        f"Embedded table for {package_name}:{kind} is invalid: {exc}"
                    ) from exc
            if path_text and replacement is None:
                candidate = Path(path_text).expanduser()
                if candidate.exists() and candidate.is_file():
                    mismatch = _fingerprint_mismatch(dataset_entry, candidate)
                    if mismatch:
                        changed_datasets.add((package_name, kind))
                        warnings.append(
                            f"The file for {package_name}:{kind} ({candidate.name}) was modified after "
                            f"this state was saved ({mismatch}); it was restored anyway, so results "
                            "may not match the saved analysis."
                        )
                    frame_by_package_kind[(package_name, kind)] = (
                        _read_table_from_path(str(candidate)),
                        filename or candidate.name,
                        str(candidate),
                    )
                    continue
            if replacement is None:
                raise RestoreStateError(
                    f"Missing replacement for dataset {package_name}:{kind}."
                )
            content = _read_replacement_bytes(
                replacement,
                label=f"Replacement file for {package_name}:{kind}",
            )
            mismatch = _compare_fingerprint(dataset_entry, {
                "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            })
            if not dataset_entry.get("sha256"):
                mismatch = "no saved SHA-256 fingerprint; file identity could not be verified"
            if mismatch:
                changed_datasets.add((package_name, kind))
                warnings.append(
                    f"The replacement file for {package_name}:{kind} does not have a verified match "
                    f"to the saved source ({mismatch}); results may not match the saved analysis."
                )
            frame = read_dataframe(replacement.file.filename or filename, io.BytesIO(content))
            frame_by_package_kind[(package_name, kind)] = (
                frame,
                replacement.file.filename or filename,
                replacement.source_path if allow_local_paths else None,
            )
            warnings.append(f"Restored {package_name}:{kind} from uploaded replacement file.")

        for kind in _TABLE_KINDS:
            prepared_table = frame_by_package_kind.get((package_name, kind))
            entry = datasets.get(kind)
            if prepared_table is None or not isinstance(entry, dict) or "tableSha256" not in entry:
                continue
            if entry["tableSha256"] != _table_fingerprint(prepared_table[0]):
                changed_datasets.add((package_name, kind))
                warnings.append(
                    f"The restored table for {package_name}:{kind} differs from the data loaded "
                    "in the saved analysis; the source may have changed before the state was saved. "
                    "Results will be recomputed without the saved imputed data."
                )

        peptide_entry = datasets.get("peptide")
        if peptide_entry is None:
            continue
        if not isinstance(peptide_entry, dict):
            raise RestoreStateError(f"Saved dataset entry for {package_name}:peptide is invalid.")
        peptide_filename = _optional_text(peptide_entry.get("filename")) or "peptide.tsv"
        peptide_path = _optional_text(peptide_entry.get("path")) if allow_local_paths else None
        replacement = replacements.get((package_name, "peptide"))
        if peptide_path and replacement is None:
            candidate = Path(peptide_path).expanduser()
            if candidate.exists() and candidate.is_file():
                peptide_path_by_package[package_name] = (str(candidate), str(candidate))
                continue
        if replacement is None:
            raise RestoreStateError(
                f"Missing replacement for dataset {package_name}:peptide."
            )
        if allow_local_paths and replacement.source_path:
            peptide_path_by_package[package_name] = (
                replacement.source_path,
                replacement.source_path,
            )
        else:
            content = _read_replacement_bytes(
                replacement,
                label=f"Replacement file for {package_name}:peptide",
            )
            target = _restore_upload_dir() / f"{uuid4().hex}_{Path(peptide_filename).name}"
            write_private_bytes(target, content)
            peptide_path_by_package[package_name] = (str(target.resolve()), None)
        warnings.append(f"Restored {package_name}:peptide from uploaded replacement file.")

    return PreparedRestoreInput(
        frame_by_package_kind=frame_by_package_kind,
        peptide_path_by_package=peptide_path_by_package,
        warnings=warnings,
        changed_datasets=changed_datasets,
    )


def _restore_peptide_metadata_payload(
    payload: Any,
    *,
    package_name: str,
    warnings: list[str],
) -> None:
    if not isinstance(payload, dict):
        return
    frame_payload = payload.get("frame")
    if frame_payload is None:
        return
    try:
        frame = _frame_from_payload(frame_payload)
        filename = str(payload.get("filename", "")).strip() or "peptide_metadata.csv"
        save_peptide_metadata(filename=filename, frame=frame, package_name=package_name)
    except Exception:
        warnings.append(f"Failed to restore peptide metadata table for {package_name}.")


def _apply_prepared_restore_state(
    state: dict[str, Any],
    prepared: PreparedRestoreInput,
) -> RestoreApplyResult:
    backend = state.get("backend")
    if not isinstance(backend, dict):
        raise RestoreStateError("Restore file is missing backend state.")
    packages = backend.get("packages")
    if not isinstance(packages, list):
        raise RestoreStateError("Restore file is missing package list.")

    reset_all_annotations()
    reset_all_uploaded_metadata()
    reset_all_datasets()
    reset_condition_palettes()
    clear_peptide_metadata()

    restored_datasets: list[str] = []
    restored_annotations: list[str] = []
    warnings = list(prepared.warnings)

    package_names: list[str] = []
    deferred_auto_metadata: list[DeferredAutoMetadataRestore] = []
    metadata_active_profile_by_package: dict[str, str] = {}
    for package_entry in packages:
        if not isinstance(package_entry, dict):
            continue
        package_name = str(package_entry.get("name", "")).strip()
        if not package_name:
            continue
        package_names.append(package_name)
        create_package(package_name)

    for package_entry in packages:
        if not isinstance(package_entry, dict):
            continue
        package_name = str(package_entry.get("name", "")).strip()
        if not package_name:
            continue
        set_active_package(package_name)
        datasets = package_entry.get("datasets")
        if not isinstance(datasets, dict):
            continue

        for kind in _TABLE_KINDS:
            if datasets.get(kind) is None:
                continue
            prepared_entry = prepared.frame_by_package_kind.get((package_name, kind))
            if prepared_entry is None:
                continue
            frame, filename, source_path = prepared_entry
            save_table_dataset(
                filename=filename,
                kind=kind,
                frame=frame,
                package_name=package_name,
                source_path=source_path,
                phosprot_aggregation=_coerce_phosprot_aggregation(datasets[kind].get("phosprotAggregation")) if kind == "phosprot" else None,
            )
            restored_datasets.append(f"{package_name}:{kind}")

        if datasets.get("peptide") is not None:
            peptide_entry = prepared.peptide_path_by_package.get(package_name)
            if peptide_entry is not None:
                path_value, source_path = peptide_entry
                stored = save_peptide_path(path_value, package_name=package_name)
                if source_path:
                    stored.path = source_path
                restored_datasets.append(f"{package_name}:peptide")

        metadata_block = package_entry.get("metadata")
        metadata_active_profile = DEFAULT_METADATA_PROFILE_NAME
        if isinstance(metadata_block, dict):
            metadata_active_profile = str(
                metadata_block.get("activeProfile", DEFAULT_METADATA_PROFILE_NAME)
            ).strip() or DEFAULT_METADATA_PROFILE_NAME
            metadata_active_profile_by_package[package_name] = metadata_active_profile
            metadata_profiles = metadata_block.get("profiles")
            if isinstance(metadata_profiles, list):
                for profile_entry in metadata_profiles:
                    if not isinstance(profile_entry, dict):
                        continue
                    profile_name = str(profile_entry.get("name", "")).strip()
                    if not profile_name:
                        continue
                    is_auto_generated_profile = any(
                        isinstance(profile_entry.get(metadata_kind), dict)
                        and bool(profile_entry[metadata_kind].get("autoGenerated"))
                        for metadata_kind in _METADATA_KINDS
                    )
                    if (
                        profile_name != DEFAULT_METADATA_PROFILE_NAME
                        and not is_auto_generated_profile
                    ):
                        try:
                            create_metadata_profile(profile_name, package_name=package_name)
                        except ValueError:
                            pass
                for profile_entry in metadata_profiles:
                    if not isinstance(profile_entry, dict):
                        continue
                    profile_name = str(profile_entry.get("name", "")).strip()
                    if not profile_name:
                        continue
                    for metadata_kind in _METADATA_KINDS:
                        metadata_payload = profile_entry.get(metadata_kind)
                        if not isinstance(metadata_payload, dict):
                            continue
                        frame_payload = metadata_payload.get("frame")
                        if frame_payload is None:
                            continue
                        metadata_filename = (
                            str(metadata_payload.get("filename", "")).strip()
                            or f"{metadata_kind}_metadata.csv"
                        )
                        if bool(metadata_payload.get("autoGenerated")):
                            deferred_auto_metadata.append(
                                DeferredAutoMetadataRestore(
                                    package_name=package_name,
                                    profile_name=profile_name,
                                    metadata_kind=metadata_kind,
                                    filename=metadata_filename,
                                    frame_payload=frame_payload,
                                )
                            )
                            continue
                        try:
                            metadata_frame = _frame_from_payload(frame_payload)
                        except Exception:
                            warnings.append(
                                f"Skipped invalid metadata frame for {package_name}:{profile_name}:{metadata_kind}."
                            )
                            continue
                        save_uploaded_metadata(
                            metadata_kind,
                            metadata_filename,
                            metadata_frame,
                            package_name=package_name,
                            profile_name=profile_name,
                        )

        _restore_peptide_metadata_payload(
            package_entry.get("peptideMetadata"),
            package_name=package_name,
            warnings=warnings,
        )

    for deferred in deferred_auto_metadata:
        restored_metadata = get_uploaded_metadata(
            deferred.metadata_kind,
            package_name=deferred.package_name,
            profile_name=deferred.profile_name,
        )
        if restored_metadata is not None and restored_metadata.auto_generated:
            continue
        try:
            metadata_frame = _frame_from_payload(deferred.frame_payload)
        except Exception:
            warnings.append(
                f"Skipped invalid metadata frame for {deferred.package_name}:{deferred.profile_name}:{deferred.metadata_kind}."
            )
            continue
        save_uploaded_metadata(
            deferred.metadata_kind,
            deferred.filename,
            metadata_frame,
            package_name=deferred.package_name,
            profile_name=deferred.profile_name,
        )
        warnings.append(
            f"Restored {deferred.package_name}:{deferred.profile_name}:{deferred.metadata_kind} "
            "as a manual metadata profile because the derived profile could not be regenerated."
        )

    for package_entry in packages:
        if not isinstance(package_entry, dict):
            continue
        package_name = str(package_entry.get("name", "")).strip()
        if not package_name:
            continue
        set_active_package(package_name)
        annotations_payload = package_entry.get("annotations")
        if isinstance(annotations_payload, list):
            for annotation_entry in annotations_payload:
                if not isinstance(annotation_entry, dict):
                    continue
                profile_name = str(annotation_entry.get("profile", "")).strip() or DEFAULT_METADATA_PROFILE_NAME
                kind = _normalize_table_kind(annotation_entry.get("kind"))
                if kind is None:
                    continue
                dataset = get_current_dataset(kind, package_name=package_name)
                if dataset is None or not hasattr(dataset, "frame"):
                    warnings.append(
                        f"Skipped annotation restore for {package_name}:{profile_name}:{kind} because dataset is missing."
                    )
                    continue
                frame_payload = annotation_entry.get("metadataFrame")
                if frame_payload is None:
                    continue
                try:
                    metadata_frame = _frame_from_payload(frame_payload)
                except Exception:
                    warnings.append(
                        f"Skipped annotation restore for {package_name}:{profile_name}:{kind} due to invalid metadata frame."
                    )
                    continue
                if metadata_frame.empty:
                    continue
                filter_config = _coerce_filter_config(
                    annotation_entry.get("filter"),
                    warnings,
                    f"{package_name}:{profile_name}:{kind}: ",
                )
                if kind == "phosprot":
                    filter_config = phosprot_filter_config(filter_config)
                is_log2_transformed = bool(annotation_entry.get("isLog2Transformed", True))
                log2_auto_detected = bool(annotation_entry.get("log2AutoDetected", False))
                metadata_source = _normalize_metadata_source(annotation_entry.get("metadataSource"))
                imputation, imputation_problem = _coerce_imputation(annotation_entry.get("imputation"))
                imputed_data = pd.DataFrame()
                imputed_payload = annotation_entry.get("imputedFrame")
                if imputed_payload is not None:
                    try:
                        imputed_data = _frame_from_payload(imputed_payload)
                    except Exception:
                        warnings.append(
                            f"Discarded invalid imputed data for "
                            f"{package_name}:{profile_name}:{kind}."
                        )
                required_imputed_samples = metadata_frame["sample"].astype(str).tolist()
                if not imputed_data.empty and (package_name, kind) in prepared.changed_datasets:
                    warnings.append(
                        f"Discarded stale imputed data for {package_name}:{profile_name}:{kind} "
                        "because the source file no longer matches its saved fingerprint. "
                        "Run imputation again before selecting imputed results."
                    )
                    imputed_data = pd.DataFrame()
                if not imputed_data.empty and any(
                    sample not in imputed_data.columns for sample in required_imputed_samples
                ):
                    warnings.append(
                        f"Discarded stale imputed data for {package_name}:{profile_name}:{kind} "
                        "because sample columns no longer match."
                    )
                    imputed_data = pd.DataFrame()
                if imputation is None and imputation_problem is not None and not imputed_data.empty:
                    # The matrix is intact; only its description is unreadable.
                    # Keep the matrix and say so, rather than dropping every
                    # "imputed data" plot back to the raw matrix in silence.
                    warnings.append(
                        f"The imputation record for {package_name}:{profile_name}:{kind} could not be "
                        f"read ({imputation_problem}); the imputed matrix was kept, its parameters are unknown."
                    )
                    imputation = AnnotationImputationInfo(mode="unknown", applied=True)
                elif imputation is None and imputation_problem is not None:
                    warnings.append(
                        f"The imputation record for {package_name}:{profile_name}:{kind} could not be "
                        f"read ({imputation_problem}) and no imputed matrix was saved; imputation is not restored."
                    )
                if imputation is None:
                    imputed_data = pd.DataFrame()
                elif imputed_data.empty:
                    imputation = imputation.model_copy(update={"applied": False})
                else:
                    imputation = imputation.model_copy(update={"applied": True})
                try:
                    computed = compute_annotation_from_metadata(
                        data=dataset.frame,
                        metadata=metadata_frame,
                        is_log2_transformed=is_log2_transformed,
                        min_present=filter_config.minPresent,
                        filter_mode=filter_config.mode,
                        filter_method=filter_config.method,
                        min_percentage=filter_config.minPercentage,
                        normalization=filter_config.normalization,
                    )
                    save_annotation(
                        kind=kind,
                        source_data=dataset.frame,
                        metadata=computed.metadata,
                        log2_data=computed.log2_data,
                        filtered_data=computed.filtered_data,
                        is_log2_transformed=is_log2_transformed,
                        metadata_source=metadata_source,
                        filter_config=filter_config,
                        auto_detected=computed.auto_detected,
                        warnings=computed.warnings,
                        log2_auto_detected=log2_auto_detected,
                        imputation=imputation,
                        imputed_data=imputed_data,
                        package_name=package_name,
                        metadata_profile_name=profile_name,
                        phosprot_aggregation=_coerce_phosprot_aggregation(
                            annotation_entry.get("phosprotAggregation")
                        ),
                    )
                    restored_annotations.append(f"{package_name}:{profile_name}:{kind}")
                except Exception as exc:
                    LOGGER.exception(
                        "Failed to restore annotation %s:%s:%s",
                        package_name,
                        profile_name,
                        kind,
                    )
                    warnings.append(
                        f"Failed to restore annotation {package_name}:{profile_name}:{kind}. "
                        "Check the server log."
                    )

        try:
            set_active_profile(
                metadata_active_profile_by_package.get(
                    package_name,
                    DEFAULT_METADATA_PROFILE_NAME,
                ),
                package_name=package_name,
            )
        except Exception:
            try:
                set_active_profile(DEFAULT_METADATA_PROFILE_NAME, package_name=package_name)
            except Exception:
                pass

    palettes_payload = backend.get("conditionPalettes")
    if isinstance(palettes_payload, dict):
        for kind in _TABLE_KINDS:
            palette_value = palettes_payload.get(kind)
            if isinstance(palette_value, dict):
                set_condition_palette(kind, {str(key): str(value) for key, value in palette_value.items()})

    active_package = str(backend.get("activePackage", "")).strip()
    if active_package and active_package in package_names:
        set_active_package(active_package)
    elif package_names:
        set_active_package(package_names[0])

    return RestoreApplyResult(
        warnings=warnings,
        restored_datasets=restored_datasets,
        restored_annotations=restored_annotations,
    )


def apply_restore_state(
    state: dict[str, Any],
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
    *, allow_local_paths: bool = True,
) -> RestoreApplyResult:
    """Apply a restore atomically within the current browser session.

    Input files are fully read before the live stores are touched. If any
    unexpected failure occurs after clearing begins, every participating store
    is replaced with its exact pre-restore snapshot before the error escapes.
    Separate sessions use separate locks and therefore remain independent.
    """
    prepared = _prepare_restore_inputs(state, replacements, allow_local_paths=allow_local_paths)
    with _current_restore_lock():
        snapshots = (
            snapshot_dataset_session_state(),
            snapshot_metadata_session_state(),
            snapshot_annotation_session_state(),
            snapshot_condition_palette_session_state(),
            snapshot_peptide_metadata_session_state(),
        )
        try:
            return _apply_prepared_restore_state(state, prepared)
        except Exception:
            restore_dataset_session_state(snapshots[0])
            restore_metadata_session_state(snapshots[1])
            restore_annotation_session_state(snapshots[2])
            restore_condition_palette_session_state(snapshots[3])
            restore_peptide_metadata_session_state(snapshots[4])
            LOGGER.exception("Restore failed; the previous session state was rolled back")
            raise


def decode_restore_blob(blob: bytes) -> dict[str, Any]:
    return _parse_state_blob(blob)

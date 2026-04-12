from __future__ import annotations

import gzip
import io
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal
from uuid import uuid4

import pandas as pd
from fastapi import UploadFile

from app.app_version import APP_VERSION
from app.schemas.annotation import AnnotationFilterConfig, AnnotationImputationInfo, AnnotationKind
from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.annotation_store import (
    get_annotation,
    list_annotation_profiles,
    reset_all_annotations,
    save_annotation,
)
from app.services.condition_palette_store import get_condition_palette, reset_condition_palettes, set_condition_palette
from app.services.dataset_reader import read_dataframe
from app.services.dataset_store import (
    create_package,
    get_active_package,
    get_all_current_datasets,
    get_current_dataset,
    list_packages,
    reset_all_datasets,
    save_peptide_path,
    save_table_dataset,
    set_active_package,
)
from app.services.metadata_upload_store import (
    DEFAULT_METADATA_PROFILE_NAME,
    create_profile as create_metadata_profile,
    get_active_profile,
    get_uploaded_metadata,
    list_profiles,
    reset_all_uploaded_metadata,
    save_uploaded_metadata,
    set_active_profile,
)
from app.services.peptide_metadata_store import clear_peptide_metadata, get_peptide_metadata, save_peptide_metadata

TableKind = Literal["protein", "phospho", "phosprot"]
DatasetKind = Literal["protein", "phospho", "phosprot", "peptide"]
_TABLE_KINDS: tuple[TableKind, ...] = ("protein", "phospho", "phosprot")
_DATASET_KINDS: tuple[DatasetKind, ...] = ("protein", "phospho", "phosprot", "peptide")
_METADATA_KINDS: tuple[Literal["protein", "phospho"], ...] = ("protein", "phospho")
_STATE_FORMAT = "copylot_state_v1"


class RestoreStateError(ValueError):
    pass


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


@dataclass
class ReplacementInput:
    file: UploadFile
    source_path: str | None = None


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


def _coerce_filter_config(payload: Any) -> AnnotationFilterConfig:
    if not isinstance(payload, dict):
        return AnnotationFilterConfig()
    min_present_raw = payload.get("minPresent", 0)
    mode_raw = str(payload.get("mode", "per_group")).strip()
    min_present = int(min_present_raw) if isinstance(min_present_raw, (int, float)) else 0
    if min_present < 0:
        min_present = 0
    if mode_raw not in {"per_group", "in_at_least_one_group"}:
        mode_raw = "per_group"
    return AnnotationFilterConfig(minPresent=min_present, mode=mode_raw)  # type: ignore[arg-type]


def _coerce_imputation(payload: Any) -> AnnotationImputationInfo | None:
    if not isinstance(payload, dict):
        return None
    try:
        return AnnotationImputationInfo(**payload)
    except Exception:
        return None


def _normalize_metadata_source(payload: Any) -> Literal["manual", "auto", "uploaded", "shared_phospho"]:
    text = str(payload or "").strip().lower()
    if text in {"manual", "auto", "uploaded", "shared_phospho"}:
        return text  # type: ignore[return-value]
    return "manual"


def _restore_upload_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "ProteomicsCoPYlot" / "restore_uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _table_backup_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "ProteomicsCoPYlot" / "table_uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


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
        frame.to_csv(target, sep="\t", index=False)
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
    raw: bytes
    try:
        raw = gzip.decompress(blob)
    except Exception:
        raw = blob
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


def export_state_blob(*, ui_state: dict[str, Any] | None = None) -> bytes:
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
            dataset_payload[kind] = {
                "filename": str(getattr(stored, "filename", "") or ""),
                "path": _ensure_exportable_table_path(stored),
            }
        peptide_stored = current.get("peptide")
        dataset_payload["peptide"] = (
            None
            if peptide_stored is None
            else {
                "filename": str(getattr(peptide_stored, "filename", "") or ""),
                "path": _optional_text(getattr(peptide_stored, "path", None)),
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
                        "metadataSource": str(getattr(stored_annotation, "metadata_source", "manual")),
                        "filter": {
                            "minPresent": int(stored_annotation.filter_config.minPresent),
                            "mode": str(stored_annotation.filter_config.mode),
                        },
                        "imputation": (
                            stored_annotation.imputation.model_dump()
                            if stored_annotation.imputation is not None
                            else None
                        ),
                        "metadataFrame": _frame_to_payload(stored_annotation.metadata),
                    }
                )

        packages_payload.append(
            {
                "name": package_name,
                "datasets": dataset_payload,
                "metadata": {
                    "activeProfile": get_active_profile(package_name=package_name),
                    "profiles": metadata_profiles_payload,
                },
                "annotations": annotation_payload,
            }
        )

    peptide_metadata = get_peptide_metadata()
    payload: dict[str, Any] = {
        "format": _STATE_FORMAT,
        "appVersion": APP_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "uiState": ui_state or {},
        "backend": {
            "activePackage": active_package,
            "packages": packages_payload,
            "conditionPalettes": {
                "protein": get_condition_palette("protein"),
                "phospho": get_condition_palette("phospho"),
                "phosprot": get_condition_palette("phosprot"),
            },
            "peptideMetadata": (
                None
                if peptide_metadata is None
                else {
                    "filename": peptide_metadata.filename,
                    "frame": _frame_to_payload(peptide_metadata.frame),
                }
            ),
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
    if not manifest_text:
        raise RestoreStateError("Replacement file manifest is required when replacement files are provided.")
    try:
        parsed = json.loads(manifest_text)
    except Exception as exc:
        raise RestoreStateError(f"Replacement manifest is invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise RestoreStateError("Replacement manifest must be a JSON array.")
    if len(parsed) != len(files):
        raise RestoreStateError("Replacement manifest size does not match number of replacement files.")

    mapped: dict[tuple[str, DatasetKind], ReplacementInput] = {}
    for index, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise RestoreStateError("Replacement manifest entries must be objects.")
        package_name = str(entry.get("packageName", "")).strip()
        kind = _normalize_dataset_kind(entry.get("kind"))
        source_path = _optional_text(entry.get("sourcePath"))
        if not package_name or kind is None:
            raise RestoreStateError("Replacement manifest entry is missing packageName or kind.")
        mapped[(package_name, kind)] = ReplacementInput(
            file=files[index],
            source_path=source_path,
        )
    return mapped


def inspect_missing_files(
    state: dict[str, Any],
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
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
            path_text = _optional_text(dataset_entry.get("path"))
            has_replacement = (package_name, kind) in replacements
            if path_text:
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
) -> PreparedRestoreInput:
    backend = state.get("backend")
    if not isinstance(backend, dict):
        raise RestoreStateError("Restore file is missing backend state.")
    packages = backend.get("packages")
    if not isinstance(packages, list):
        raise RestoreStateError("Restore file is missing package list.")

    frame_by_package_kind: dict[tuple[str, TableKind], tuple[pd.DataFrame, str, str | None]] = {}
    peptide_path_by_package: dict[str, tuple[str, str | None]] = {}
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
            path_text = _optional_text(dataset_entry.get("path"))
            replacement = replacements.get((package_name, kind))
            if path_text:
                candidate = Path(path_text).expanduser()
                if candidate.exists() and candidate.is_file():
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
            content = replacement.file.read()
            frame = read_dataframe(replacement.file.filename or filename, io.BytesIO(content))
            frame_by_package_kind[(package_name, kind)] = (
                frame,
                replacement.file.filename or filename,
                replacement.source_path,
            )
            warnings.append(f"Restored {package_name}:{kind} from uploaded replacement file.")

        peptide_entry = datasets.get("peptide")
        if peptide_entry is None:
            continue
        if not isinstance(peptide_entry, dict):
            raise RestoreStateError(f"Saved dataset entry for {package_name}:peptide is invalid.")
        peptide_filename = _optional_text(peptide_entry.get("filename")) or "peptide.tsv"
        peptide_path = _optional_text(peptide_entry.get("path"))
        replacement = replacements.get((package_name, "peptide"))
        if peptide_path:
            candidate = Path(peptide_path).expanduser()
            if candidate.exists() and candidate.is_file():
                peptide_path_by_package[package_name] = (str(candidate), str(candidate))
                continue
        if replacement is None:
            raise RestoreStateError(
                f"Missing replacement for dataset {package_name}:peptide."
            )
        if replacement.source_path:
            peptide_path_by_package[package_name] = (
                replacement.source_path,
                replacement.source_path,
            )
        else:
            content = replacement.file.read()
            target = _restore_upload_dir() / f"{uuid4().hex}_{Path(peptide_filename).name}"
            target.write_bytes(content)
            peptide_path_by_package[package_name] = (str(target.resolve()), None)
        warnings.append(f"Restored {package_name}:peptide from uploaded replacement file.")

    return PreparedRestoreInput(
        frame_by_package_kind=frame_by_package_kind,
        peptide_path_by_package=peptide_path_by_package,
        warnings=warnings,
    )


def apply_restore_state(
    state: dict[str, Any],
    replacements: dict[tuple[str, DatasetKind], ReplacementInput],
) -> RestoreApplyResult:
    prepared = _prepare_restore_inputs(state, replacements)
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
                    if profile_name != DEFAULT_METADATA_PROFILE_NAME:
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
                filter_config = _coerce_filter_config(annotation_entry.get("filter"))
                is_log2_transformed = bool(annotation_entry.get("isLog2Transformed", True))
                metadata_source = _normalize_metadata_source(annotation_entry.get("metadataSource"))
                imputation = _coerce_imputation(annotation_entry.get("imputation"))
                try:
                    computed = compute_annotation_from_metadata(
                        data=dataset.frame,
                        metadata=metadata_frame,
                        is_log2_transformed=is_log2_transformed,
                        min_present=filter_config.minPresent,
                        filter_mode=filter_config.mode,
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
                        imputation=imputation,
                        package_name=package_name,
                        metadata_profile_name=profile_name,
                    )
                    restored_annotations.append(f"{package_name}:{profile_name}:{kind}")
                except Exception as exc:
                    warnings.append(
                        f"Failed to restore annotation {package_name}:{profile_name}:{kind}: {exc}"
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

    peptide_metadata_payload = backend.get("peptideMetadata")
    if isinstance(peptide_metadata_payload, dict):
        frame_payload = peptide_metadata_payload.get("frame")
        if frame_payload is not None:
            try:
                frame = _frame_from_payload(frame_payload)
                filename = str(peptide_metadata_payload.get("filename", "")).strip() or "peptide_metadata.csv"
                save_peptide_metadata(filename=filename, frame=frame)
            except Exception:
                warnings.append("Failed to restore peptide metadata table.")

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


def decode_restore_blob(blob: bytes) -> dict[str, Any]:
    return _parse_state_blob(blob)

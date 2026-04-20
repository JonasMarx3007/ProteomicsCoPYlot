from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationImputationInfo,
    AnnotationKind,
    MetadataSource,
)
from app.services.dataset_store import get_active_package
from app.services.metadata_upload_store import get_active_profile
from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id


@dataclass
class StoredAnnotation:
    kind: AnnotationKind
    source_data: pd.DataFrame
    metadata: pd.DataFrame
    log2_data: pd.DataFrame
    filtered_data: pd.DataFrame
    is_log2_transformed: bool
    metadata_source: MetadataSource
    filter_config: AnnotationFilterConfig
    auto_detected: bool
    warnings: list[str]
    imputation: AnnotationImputationInfo | None
    created_at: str


def _empty_annotation_state() -> dict[AnnotationKind, StoredAnnotation | None]:
    return {
        "protein": None,
        "phospho": None,
        "phosprot": None,
    }


_ANNOTATIONS_BY_SESSION: dict[
    str, dict[str, dict[str, dict[AnnotationKind, StoredAnnotation | None]]]
] = {}


def _annotations_by_package() -> dict[str, dict[str, dict[AnnotationKind, StoredAnnotation | None]]]:
    session_id = get_session_id()
    if session_id not in _ANNOTATIONS_BY_SESSION:
        _ANNOTATIONS_BY_SESSION[session_id] = {}
    return _ANNOTATIONS_BY_SESSION[session_id]


def _resolve_package(package_name: str | None) -> str:
    text = str(package_name or "").strip()
    return text or get_active_package()


def _resolve_metadata_profile(package_name: str, metadata_profile_name: str | None) -> str:
    text = str(metadata_profile_name or "").strip()
    if text:
        return text
    return get_active_profile(package_name=package_name)


def _ensure_package(package_name: str | None = None) -> str:
    resolved = _resolve_package(package_name)
    annotations = _annotations_by_package()
    if resolved not in annotations:
        annotations[resolved] = {}
    return resolved


def _profile_state(
    package_name: str | None = None,
    *,
    metadata_profile_name: str | None = None,
) -> dict[AnnotationKind, StoredAnnotation | None]:
    resolved_package = _ensure_package(package_name)
    resolved_profile = _resolve_metadata_profile(resolved_package, metadata_profile_name)
    package_profiles = _annotations_by_package()[resolved_package]
    if resolved_profile not in package_profiles:
        package_profiles[resolved_profile] = _empty_annotation_state()
    return package_profiles[resolved_profile]


def save_annotation(
    kind: AnnotationKind,
    source_data: pd.DataFrame,
    metadata: pd.DataFrame,
    log2_data: pd.DataFrame,
    filtered_data: pd.DataFrame,
    is_log2_transformed: bool,
    metadata_source: MetadataSource,
    filter_config: AnnotationFilterConfig,
    auto_detected: bool,
    warnings: list[str],
    imputation: AnnotationImputationInfo | None = None,
    *,
    package_name: str | None = None,
    metadata_profile_name: str | None = None,
) -> StoredAnnotation:
    resolved_package = _ensure_package(package_name)
    resolved_profile = _resolve_metadata_profile(resolved_package, metadata_profile_name)
    state = _profile_state(
        resolved_package,
        metadata_profile_name=resolved_profile,
    )

    stored = StoredAnnotation(
        kind=kind,
        source_data=source_data.copy(),
        metadata=metadata.copy(),
        log2_data=log2_data.copy(),
        filtered_data=filtered_data.copy(),
        is_log2_transformed=is_log2_transformed,
        metadata_source=metadata_source,
        filter_config=filter_config,
        auto_detected=auto_detected,
        warnings=list(warnings),
        imputation=imputation,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    state[kind] = stored
    invalidate_runtime_cache(f"annotation:{resolved_package}:{resolved_profile}:{kind}:updated")
    return stored


def get_annotation(
    kind: AnnotationKind,
    *,
    package_name: str | None = None,
    metadata_profile_name: str | None = None,
) -> StoredAnnotation | None:
    state = _profile_state(
        package_name,
        metadata_profile_name=metadata_profile_name,
    )
    return state.get(kind)


def list_annotation_profiles(
    *,
    package_name: str | None = None,
    include_empty: bool = False,
) -> list[str]:
    resolved_package = _ensure_package(package_name)
    profiles = _annotations_by_package()[resolved_package]
    names = [
        profile_name
        for profile_name, state in profiles.items()
        if include_empty or any(value is not None for value in state.values())
    ]
    active = get_active_profile(package_name=resolved_package)
    names_sorted = sorted(names, key=lambda value: value.lower())
    if active in names_sorted:
        return [active] + [name for name in names_sorted if name != active]
    return names_sorted


def clear_annotation(
    kind: AnnotationKind,
    *,
    package_name: str | None = None,
    metadata_profile_name: str | None = None,
    clear_all_profiles: bool = False,
) -> None:
    resolved_package = _ensure_package(package_name)
    annotations = _annotations_by_package()
    if clear_all_profiles:
        for profile, state in annotations[resolved_package].items():
            state[kind] = None
            invalidate_runtime_cache(f"annotation:{resolved_package}:{profile}:{kind}:cleared")
        return

    resolved_profile = _resolve_metadata_profile(resolved_package, metadata_profile_name)
    state = _profile_state(
        resolved_package,
        metadata_profile_name=resolved_profile,
    )
    state[kind] = None
    invalidate_runtime_cache(f"annotation:{resolved_package}:{resolved_profile}:{kind}:cleared")


def rename_package(old_name: str, new_name: str) -> None:
    old_key = str(old_name or "").strip()
    new_key = str(new_name or "").strip()
    if not old_key or not new_key or old_key == new_key:
        return
    annotations = _annotations_by_package()
    if old_key not in annotations:
        return
    if new_key in annotations:
        raise ValueError(f"Annotation package '{new_key}' already exists.")
    annotations[new_key] = annotations.pop(old_key)
    invalidate_runtime_cache(f"annotation-package:{old_key}:renamed:{new_key}")


def rename_metadata_profile(
    old_name: str,
    new_name: str,
    *,
    package_name: str | None = None,
) -> None:
    resolved_package = _ensure_package(package_name)
    old_key = str(old_name or "").strip()
    new_key = str(new_name or "").strip()
    if not old_key or not new_key or old_key == new_key:
        return
    package_profiles = _annotations_by_package()[resolved_package]
    if old_key not in package_profiles:
        return
    if new_key in package_profiles:
        raise ValueError(f"Annotation profile '{new_key}' already exists.")
    package_profiles[new_key] = package_profiles.pop(old_key)
    invalidate_runtime_cache(
        f"annotation:{resolved_package}:metadata-profile:{old_key}:renamed:{new_key}"
    )


def reset_all_annotations(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _ANNOTATIONS_BY_SESSION.clear()
    else:
        _ANNOTATIONS_BY_SESSION[get_session_id()] = {}
    invalidate_runtime_cache("annotation:reset-all")

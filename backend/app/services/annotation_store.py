from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from app.schemas.annotation import (
    AnnotationFilterConfig,
    AnnotationImputationInfo,
    AnnotationKind,
    MetadataSource,
    SamplePairAssignment,
    PhosprotLineage,
)
from app.services.dataset_store import get_active_package
from app.services.functions import paired_sample_columns
from app.services.metadata_upload_store import (
    get_active_profile,
    update_uploaded_metadata_pair_ids,
)
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
    log2_auto_detected: bool
    warnings: list[str]
    imputation: AnnotationImputationInfo | None
    imputed_data: pd.DataFrame
    created_at: str
    # How a "phosprot" frame was produced. ``robust_site_median`` centres every
    # site on its own across-sample median, so its values are ratios rather than
    # abundances; the other modes and a direct upload carry real intensities.
    # None for the "protein" and "phospho" kinds.
    phosprot_aggregation: str | None = None
    phosprot_lineage: PhosprotLineage | None = None


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
    log2_auto_detected: bool = False,
    imputation: AnnotationImputationInfo | None = None,
    imputed_data: pd.DataFrame | None = None,
    *,
    package_name: str | None = None,
    metadata_profile_name: str | None = None,
    phosprot_aggregation: str | None = None,
    phosprot_lineage: PhosprotLineage | None = None,
) -> StoredAnnotation:
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
        log2_auto_detected=log2_auto_detected,
        warnings=list(warnings),
        imputation=imputation,
        imputed_data=(imputed_data.copy() if imputed_data is not None else pd.DataFrame()),
        created_at=datetime.now(timezone.utc).isoformat(),
        phosprot_aggregation=phosprot_aggregation,
        phosprot_lineage=phosprot_lineage.model_copy(deep=True) if phosprot_lineage else None,
    )
    return store_prepared_annotation(stored, package_name=package_name, metadata_profile_name=metadata_profile_name)


def store_prepared_annotation(
    stored: StoredAnnotation,
    *,
    package_name: str | None = None,
    metadata_profile_name: str | None = None,
) -> StoredAnnotation:
    state = _profile_state(package_name, metadata_profile_name=metadata_profile_name)
    state[stored.kind] = stored
    invalidate_runtime_cache("annotation:updated")
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


def preserve_annotation_pair_ids(
    kind: AnnotationKind,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    stored = get_annotation(kind)
    if stored is None or "pair_id" not in stored.metadata.columns:
        return metadata
    required_columns = {"sample", "condition"}
    if not required_columns.issubset(metadata.columns) or not required_columns.issubset(
        stored.metadata.columns
    ):
        return metadata
    if metadata["sample"].duplicated().any() or stored.metadata["sample"].duplicated().any():
        return metadata

    previous_conditions = dict(
        stored.metadata[["sample", "condition"]].astype(str).itertuples(index=False, name=None)
    )
    current_conditions = dict(
        metadata[["sample", "condition"]].astype(str).itertuples(index=False, name=None)
    )
    if previous_conditions != current_conditions:
        return metadata

    previous_pair_ids = {
        str(sample): str(pair_id).strip()
        for sample, pair_id in stored.metadata[["sample", "pair_id"]].itertuples(
            index=False, name=None
        )
        if pd.notna(pair_id) and str(pair_id).strip()
    }
    if not previous_pair_ids:
        return metadata

    preserved = metadata.copy()
    if "pair_id" not in preserved.columns:
        preserved["pair_id"] = ""
    current_pair_ids = preserved["pair_id"].where(pd.notna(preserved["pair_id"]), "").astype(str)
    inherited_pair_ids = preserved["sample"].astype(str).map(previous_pair_ids).fillna("")
    preserved["pair_id"] = current_pair_ids.where(
        current_pair_ids.str.strip() != "",
        inherited_pair_ids,
    )
    return preserved


def update_annotation_pairing(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    pairs: list[SamplePairAssignment],
) -> StoredAnnotation:
    stored = get_annotation(kind)
    if stored is None:
        raise ValueError(f"No {kind} annotation is available.")

    left_condition = str(condition1).strip()
    right_condition = str(condition2).strip()
    if not left_condition or not right_condition or left_condition == right_condition:
        raise ValueError("Pairing requires two different conditions.")

    metadata = stored.metadata.copy()
    left_available = metadata.loc[
        metadata["condition"].astype(str) == left_condition, "sample"
    ].astype(str).tolist()
    right_available = metadata.loc[
        metadata["condition"].astype(str) == right_condition, "sample"
    ].astype(str).tolist()
    if not left_available or not right_available:
        raise ValueError("Both selected conditions must contain annotated samples.")

    left_samples = [str(pair.condition1Sample) for pair in pairs]
    right_samples = [str(pair.condition2Sample) for pair in pairs]
    if any(not sample.strip() for sample in [*left_samples, *right_samples]):
        raise ValueError("Sample names must not be blank.")
    if len(set(left_samples)) != len(left_samples):
        raise ValueError(f"Each sample in condition '{left_condition}' can be paired only once.")
    if len(set(right_samples)) != len(right_samples):
        raise ValueError(f"Each sample in condition '{right_condition}' can be paired only once.")

    unknown = sorted(set(left_samples) - set(left_available))
    if unknown:
        raise ValueError(
            f"Pairing contains samples outside condition '{left_condition}': {unknown}."
        )
    unknown = sorted(set(right_samples) - set(right_available))
    if unknown:
        raise ValueError(
            f"Pairing contains samples outside condition '{right_condition}': {unknown}."
        )

    if "pair_id" not in metadata.columns:
        metadata["pair_id"] = ""
    existing_pair_ids = {
        str(sample): str(pair_id).strip()
        for sample, pair_id in metadata[["sample", "pair_id"]].itertuples(
            index=False, name=None
        )
        if pd.notna(pair_id) and str(pair_id).strip()
    }
    target_rows = metadata["condition"].astype(str).isin([left_condition, right_condition])
    reserved_pair_ids = {
        str(pair_id).strip()
        for pair_id in metadata.loc[~target_rows, "pair_id"].tolist()
        if pd.notna(pair_id) and str(pair_id).strip()
    }
    metadata.loc[target_rows, "pair_id"] = ""
    assigned_pair_ids: set[str] = set()
    for index, pair in enumerate(zip(left_samples, right_samples), start=1):
        candidates = [
            existing_pair_ids.get(pair[0], ""),
            existing_pair_ids.get(pair[1], ""),
        ]
        pair_id = next(
            (
                candidate
                for candidate in candidates
                if candidate and candidate not in assigned_pair_ids
            ),
            "",
        )
        if not pair_id:
            pair_id = f"ui-pair-{index}"
            suffix = index
            while pair_id in reserved_pair_ids or pair_id in assigned_pair_ids:
                suffix += 1
                pair_id = f"ui-pair-{suffix}"
        assigned_pair_ids.add(pair_id)
        metadata.loc[metadata["sample"].astype(str) == pair[0], "pair_id"] = pair_id
        metadata.loc[metadata["sample"].astype(str) == pair[1], "pair_id"] = pair_id

    paired_sample_columns(metadata, left_condition, right_condition)
    metadata_kind = "protein" if kind == "protein" else "phospho"
    update_uploaded_metadata_pair_ids(
        metadata_kind,
        {
            str(sample): str(pair_id).strip()
            for sample, pair_id in metadata[["sample", "pair_id"]].itertuples(
                index=False, name=None
            )
        },
    )
    return save_annotation(
        kind=stored.kind,
        source_data=stored.source_data,
        metadata=metadata,
        log2_data=stored.log2_data,
        filtered_data=stored.filtered_data,
        is_log2_transformed=stored.is_log2_transformed,
        metadata_source=stored.metadata_source,
        filter_config=stored.filter_config,
        auto_detected=stored.auto_detected,
        warnings=stored.warnings,
        log2_auto_detected=stored.log2_auto_detected,
        imputation=stored.imputation,
        imputed_data=getattr(stored, "imputed_data", pd.DataFrame()),
        phosprot_aggregation=getattr(stored, "phosprot_aggregation", None),
        phosprot_lineage=getattr(stored, "phosprot_lineage", None),
    )


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
    """Follow a dataset package rename (`dataset_store.rename_package` decides it).

    Nothing to do when this session has no annotation under the old name.
    """
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


def delete_metadata_profile(
    profile_name: str,
    *,
    package_name: str | None = None,
) -> None:
    resolved_package = _ensure_package(package_name)
    key = str(profile_name or "").strip()
    if not key:
        return
    _annotations_by_package()[resolved_package].pop(key, None)
    invalidate_runtime_cache(
        f"annotation:{resolved_package}:metadata-profile:{key}:deleted"
    )


def reset_all_annotations(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _ANNOTATIONS_BY_SESSION.clear()
    else:
        _ANNOTATIONS_BY_SESSION.pop(get_session_id(), None)
    invalidate_runtime_cache("annotation:reset-all", all_sessions=all_sessions)


def snapshot_annotation_session_state():
    """Detach-safe reference used before the session entry is atomically replaced."""
    return _ANNOTATIONS_BY_SESSION.get(get_session_id())


def restore_annotation_session_state(snapshot) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _ANNOTATIONS_BY_SESSION.pop(session_id, None)
    else:
        _ANNOTATIONS_BY_SESSION[session_id] = snapshot
    invalidate_runtime_cache("annotation:transaction-restored")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

import pandas as pd

from app.schemas.annotation import MetadataAnnotationKind
from app.services.dataset_store import get_active_package
from app.services.runtime_cache import invalidate_runtime_cache

DEFAULT_METADATA_PROFILE_NAME = "Metadata"
SAMPLE_COLUMN_ALIASES = (
    "sample",
    "sample_name",
    "data_column_name",
    "data column name",
    "data_column",
    "column_name",
    "column",
)


@dataclass
class StoredUploadedMetadata:
    kind: MetadataAnnotationKind
    filename: str
    frame: pd.DataFrame
    created_at: str
    auto_generated: bool = False
    source_profiles: tuple[str, str] | None = None


def _empty_metadata_state() -> dict[MetadataAnnotationKind, StoredUploadedMetadata | None]:
    return {
        "protein": None,
        "phospho": None,
    }


_UPLOADED_METADATA_BY_PACKAGE: dict[
    str, dict[str, dict[MetadataAnnotationKind, StoredUploadedMetadata | None]]
] = {}
_ACTIVE_PROFILE_BY_PACKAGE: dict[str, str] = {}
_AUTO_COMBINED_PROFILES_BY_PACKAGE: dict[str, set[str]] = {}
_AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE: dict[
    str, dict[str, tuple[str, str]]
] = {}


def _resolve_package(package_name: str | None) -> str:
    text = str(package_name or "").strip()
    return text or get_active_package()


def _ensure_package(package_name: str | None = None) -> str:
    resolved = _resolve_package(package_name)
    if resolved not in _UPLOADED_METADATA_BY_PACKAGE:
        _UPLOADED_METADATA_BY_PACKAGE[resolved] = {
            DEFAULT_METADATA_PROFILE_NAME: _empty_metadata_state()
        }
    if resolved not in _AUTO_COMBINED_PROFILES_BY_PACKAGE:
        _AUTO_COMBINED_PROFILES_BY_PACKAGE[resolved] = set()
    if resolved not in _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE:
        _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE[resolved] = {}
    if resolved not in _ACTIVE_PROFILE_BY_PACKAGE:
        _ACTIVE_PROFILE_BY_PACKAGE[resolved] = DEFAULT_METADATA_PROFILE_NAME
    if _ACTIVE_PROFILE_BY_PACKAGE[resolved] not in _UPLOADED_METADATA_BY_PACKAGE[resolved]:
        _UPLOADED_METADATA_BY_PACKAGE[resolved][_ACTIVE_PROFILE_BY_PACKAGE[resolved]] = (
            _empty_metadata_state()
        )
    return resolved


def _normalize_profile_name(
    profile_name: str | None,
    package_name: str | None = None,
) -> str:
    package = _ensure_package(package_name)
    text = str(profile_name or "").strip()
    if text:
        return text
    return _ACTIVE_PROFILE_BY_PACKAGE.get(package, DEFAULT_METADATA_PROFILE_NAME)


def _ensure_profile(
    profile_name: str | None = None,
    *,
    package_name: str | None = None,
) -> tuple[str, str]:
    package = _ensure_package(package_name)
    resolved_profile = _normalize_profile_name(profile_name, package)
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    if resolved_profile not in profiles:
        profiles[resolved_profile] = _empty_metadata_state()
        invalidate_runtime_cache(f"metadata:{package}:profile:{resolved_profile}:created")
    return package, resolved_profile


def _profile_state(
    profile_name: str | None = None,
    *,
    package_name: str | None = None,
) -> dict[MetadataAnnotationKind, StoredUploadedMetadata | None]:
    package, resolved_profile = _ensure_profile(
        profile_name=profile_name,
        package_name=package_name,
    )
    return _UPLOADED_METADATA_BY_PACKAGE[package][resolved_profile]


def _refresh_combined_profile_keys(package_name: str) -> None:
    package = _ensure_package(package_name)
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    auto_profiles = _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(package, set())
    auto_sources = _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE.setdefault(package, {})

    manual_profiles = [
        name
        for name in profiles.keys()
        if name not in auto_profiles and name != DEFAULT_METADATA_PROFILE_NAME
    ]
    expected_sources = {
        f"{left}-{right}": (left, right)
        for left, right in combinations(manual_profiles, 2)
    }
    expected = set(expected_sources.keys())

    for name in expected:
        if name not in profiles:
            profiles[name] = _empty_metadata_state()
            invalidate_runtime_cache(f"metadata:{package}:profile:{name}:created")
        auto_profiles.add(name)
        auto_sources[name] = expected_sources[name]

    for name in list(auto_profiles):
        if name in expected:
            continue
        state = profiles.get(name)
        if state is None:
            auto_profiles.discard(name)
            auto_sources.pop(name, None)
            continue
        if _ACTIVE_PROFILE_BY_PACKAGE.get(package) == name:
            continue
        if any(value is not None for value in state.values()):
            continue
        profiles.pop(name, None)
        auto_profiles.discard(name)
        auto_sources.pop(name, None)


def _normalize_metadata_frame(frame: pd.DataFrame) -> pd.DataFrame | None:
    if frame.empty:
        return None

    normalized = frame.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    column_map = {str(column).strip().lower(): str(column).strip() for column in normalized.columns}
    sample_col = _resolve_sample_column(column_map, normalized.columns)
    if sample_col is None:
        return None
    sample_key = str(sample_col).strip().lower()
    non_sample_columns = [
        column for column in normalized.columns if str(column).strip().lower() != sample_key
    ]
    if not non_sample_columns:
        return None
    condition_col = column_map.get("condition", non_sample_columns[0])

    out = normalized[[sample_col, condition_col]].copy()
    out.columns = ["sample", "condition"]
    out["sample"] = (
        out["sample"]
        .where(pd.notna(out["sample"]), "")
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    out["condition"] = (
        out["condition"]
        .where(pd.notna(out["condition"]), "")
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    out = out[(out["sample"] != "") & (out["condition"] != "")]
    out = out.drop_duplicates(subset=["sample"], keep="first").reset_index(drop=True)
    if out.empty:
        return None
    return out


def _resolve_sample_column(
    column_map: dict[str, str],
    columns: pd.Index,
) -> str | None:
    for alias in SAMPLE_COLUMN_ALIASES:
        if alias in column_map:
            return column_map[alias]
    if len(columns) >= 2:
        return str(columns[0]).strip()
    return None


def _combine_profiles(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
) -> pd.DataFrame:
    left = _normalize_metadata_frame(left_frame)
    right = _normalize_metadata_frame(right_frame)
    if left is None or right is None:
        return pd.DataFrame(columns=["sample", "condition"])

    left_ordered = left.copy()
    left_ordered["_left_order"] = range(len(left_ordered))

    merged = left_ordered.merge(right, on="sample", how="inner", suffixes=("_left", "_right"))
    if merged.empty:
        return pd.DataFrame(columns=["sample", "condition"])

    merged["condition"] = (
        merged["condition_left"].astype(str).str.strip()
        + "-"
        + merged["condition_right"].astype(str).str.strip()
    )
    merged = merged[(merged["condition"] != "-") & (merged["condition"] != "")]
    merged = merged.sort_values("_left_order", kind="stable")
    out = merged[["sample", "condition"]].drop_duplicates(subset=["sample"], keep="first")
    return out.reset_index(drop=True)


def build_combined_metadata_frame(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
) -> pd.DataFrame:
    return _combine_profiles(left_frame=left_frame, right_frame=right_frame)


def _regenerate_combined_profiles(package_name: str, kind: MetadataAnnotationKind) -> None:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    auto_profiles = _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(package, set())

    # Remove previous auto-generated combined metadata for this kind.
    for profile_name, state in list(profiles.items()):
        stored = state.get(kind)
        if stored is not None and stored.auto_generated:
            state[kind] = None
            if all(value is None for value in state.values()) and profile_name in auto_profiles:
                if _ACTIVE_PROFILE_BY_PACKAGE.get(package) != profile_name:
                    profiles.pop(profile_name, None)
                    auto_profiles.discard(profile_name)

    manual_profiles: list[tuple[str, StoredUploadedMetadata]] = []
    for profile_name, state in list(profiles.items()):
        stored = state.get(kind)
        if stored is None or stored.auto_generated:
            continue
        manual_profiles.append((profile_name, stored))

    if len(manual_profiles) < 2:
        return

    for (left_name, left_stored), (right_name, right_stored) in combinations(manual_profiles, 2):
        combined_name = f"{left_name}-{right_name}"
        if combined_name not in profiles:
            profiles[combined_name] = _empty_metadata_state()
            invalidate_runtime_cache(f"metadata:{package}:profile:{combined_name}:created")
        state = profiles.get(combined_name)
        existing = state.get(kind) if state is not None else None
        if existing is not None and not existing.auto_generated:
            # Respect user-managed profile if it already exists with same name.
            continue

        combined_frame = _combine_profiles(
            left_frame=left_stored.frame,
            right_frame=right_stored.frame,
        )
        if combined_frame.empty:
            if state is not None:
                state[kind] = None
            continue

        state[kind] = StoredUploadedMetadata(
            kind=kind,
            filename=f"{combined_name} (auto)",
            frame=combined_frame,
            created_at=datetime.now(timezone.utc).isoformat(),
            auto_generated=True,
            source_profiles=(left_name, right_name),
        )
        auto_profiles.add(combined_name)
        invalidate_runtime_cache(f"metadata:{package}:{combined_name}:{kind}:autogenerated")


def get_active_profile(*, package_name: str | None = None) -> str:
    package = _ensure_package(package_name)
    return _ACTIVE_PROFILE_BY_PACKAGE.get(package, DEFAULT_METADATA_PROFILE_NAME)


def list_profiles(*, package_name: str | None = None) -> list[str]:
    package = _ensure_package(package_name)
    active = get_active_profile(package_name=package)
    names = list(_UPLOADED_METADATA_BY_PACKAGE[package].keys())
    # Hide empty legacy default profile once custom profiles exist.
    if DEFAULT_METADATA_PROFILE_NAME in names and len(names) > 1:
        state = _UPLOADED_METADATA_BY_PACKAGE[package][DEFAULT_METADATA_PROFILE_NAME]
        if all(value is None for value in state.values()) and active != DEFAULT_METADATA_PROFILE_NAME:
            names = [name for name in names if name != DEFAULT_METADATA_PROFILE_NAME]
    if active in names:
        return [active] + [name for name in names if name != active]
    return names


def list_auto_generated_profiles(*, package_name: str | None = None) -> list[str]:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    profiles = set(_UPLOADED_METADATA_BY_PACKAGE[package].keys())
    auto = _AUTO_COMBINED_PROFILES_BY_PACKAGE.get(package, set())
    names = sorted((profiles & auto), key=lambda value: value.lower())
    return names


def get_auto_generated_profile_sources(
    profile_name: str,
    *,
    package_name: str | None = None,
) -> tuple[str, str] | None:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    key = str(profile_name or "").strip()
    if not key:
        return None
    sources = _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE.get(package, {})
    return sources.get(key)


def set_active_profile(profile_name: str, *, package_name: str | None = None) -> str:
    package = _ensure_package(package_name)
    resolved_profile = str(profile_name or "").strip()
    if not resolved_profile:
        raise ValueError("Metadata profile name must not be empty.")
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    if resolved_profile not in profiles:
        raise ValueError(f"Metadata profile '{resolved_profile}' does not exist.")
    _ACTIVE_PROFILE_BY_PACKAGE[package] = resolved_profile
    invalidate_runtime_cache(f"metadata:{package}:profile:{resolved_profile}:active")
    return resolved_profile


def create_profile(profile_name: str, *, package_name: str | None = None) -> str:
    name = str(profile_name or "").strip()
    if not name:
        raise ValueError("Metadata profile name must not be empty.")
    package = _ensure_package(package_name)
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    if name in profiles:
        raise ValueError(f"Metadata profile '{name}' already exists.")
    profiles[name] = _empty_metadata_state()
    _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(package, set()).discard(name)
    _refresh_combined_profile_keys(package)
    _ACTIVE_PROFILE_BY_PACKAGE[package] = name
    invalidate_runtime_cache(f"metadata:{package}:profile:{name}:created")
    return name


def rename_profile(
    old_name: str,
    new_name: str,
    *,
    package_name: str | None = None,
) -> str:
    package = _ensure_package(package_name)
    old_key = str(old_name or "").strip()
    new_key = str(new_name or "").strip()
    if not old_key or not new_key:
        raise ValueError("Both original and new metadata profile names are required.")
    profiles = _UPLOADED_METADATA_BY_PACKAGE[package]
    if old_key not in profiles:
        raise ValueError(f"Metadata profile '{old_key}' does not exist.")
    if new_key in profiles and new_key != old_key:
        raise ValueError(f"Metadata profile '{new_key}' already exists.")
    if old_key == new_key:
        return old_key

    profiles[new_key] = profiles.pop(old_key)
    auto_profiles = _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(package, set())
    if old_key in auto_profiles:
        auto_profiles.discard(old_key)
        auto_profiles.add(new_key)
    _refresh_combined_profile_keys(package)
    if _ACTIVE_PROFILE_BY_PACKAGE.get(package) == old_key:
        _ACTIVE_PROFILE_BY_PACKAGE[package] = new_key
    _regenerate_combined_profiles(package, "protein")
    _regenerate_combined_profiles(package, "phospho")
    invalidate_runtime_cache(f"metadata:{package}:profile:{old_key}:renamed:{new_key}")
    return new_key


def save_uploaded_metadata(
    kind: MetadataAnnotationKind,
    filename: str,
    frame: pd.DataFrame,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
) -> StoredUploadedMetadata:
    resolved_package, resolved_profile = _ensure_profile(
        profile_name=profile_name,
        package_name=package_name,
    )
    state = _profile_state(
        profile_name=resolved_profile,
        package_name=resolved_package,
    )

    stored = StoredUploadedMetadata(
        kind=kind,
        filename=filename,
        frame=frame.copy(),
        created_at=datetime.now(timezone.utc).isoformat(),
        auto_generated=False,
        source_profiles=None,
    )
    state[kind] = stored
    _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(resolved_package, set()).discard(
        resolved_profile
    )
    _regenerate_combined_profiles(resolved_package, kind)
    invalidate_runtime_cache(
        f"metadata:{resolved_package}:{resolved_profile}:{kind}:uploaded"
    )
    return stored


def get_uploaded_metadata(
    kind: MetadataAnnotationKind,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
) -> StoredUploadedMetadata | None:
    state = _profile_state(profile_name=profile_name, package_name=package_name)
    return state.get(kind)


def clear_uploaded_metadata(
    kind: MetadataAnnotationKind,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
    clear_all_profiles: bool = False,
) -> None:
    resolved_package = _ensure_package(package_name)
    profiles = _UPLOADED_METADATA_BY_PACKAGE[resolved_package]
    auto_profiles = _AUTO_COMBINED_PROFILES_BY_PACKAGE.setdefault(resolved_package, set())
    if clear_all_profiles:
        for profile, state in list(profiles.items()):
            state[kind] = None
            invalidate_runtime_cache(f"metadata:{resolved_package}:{profile}:{kind}:cleared")
            if all(value is None for value in state.values()) and profile in auto_profiles:
                if _ACTIVE_PROFILE_BY_PACKAGE.get(resolved_package) != profile:
                    profiles.pop(profile, None)
                    auto_profiles.discard(profile)
        return

    resolved_profile = _normalize_profile_name(profile_name, resolved_package)
    state = _profile_state(profile_name=resolved_profile, package_name=resolved_package)
    state[kind] = None
    _regenerate_combined_profiles(resolved_package, kind)
    invalidate_runtime_cache(f"metadata:{resolved_package}:{resolved_profile}:{kind}:cleared")


def rename_package(old_name: str, new_name: str) -> None:
    old_key = str(old_name or "").strip()
    new_key = str(new_name or "").strip()
    if not old_key or not new_key or old_key == new_key:
        return
    if old_key not in _UPLOADED_METADATA_BY_PACKAGE:
        return
    if new_key in _UPLOADED_METADATA_BY_PACKAGE:
        raise ValueError(f"Metadata package '{new_key}' already exists.")
    _UPLOADED_METADATA_BY_PACKAGE[new_key] = _UPLOADED_METADATA_BY_PACKAGE.pop(old_key)
    if old_key in _ACTIVE_PROFILE_BY_PACKAGE:
        _ACTIVE_PROFILE_BY_PACKAGE[new_key] = _ACTIVE_PROFILE_BY_PACKAGE.pop(old_key)
    if old_key in _AUTO_COMBINED_PROFILES_BY_PACKAGE:
        _AUTO_COMBINED_PROFILES_BY_PACKAGE[new_key] = _AUTO_COMBINED_PROFILES_BY_PACKAGE.pop(old_key)
    if old_key in _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE:
        _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE[new_key] = _AUTO_COMBINED_PROFILE_SOURCES_BY_PACKAGE.pop(
            old_key
        )
    invalidate_runtime_cache(f"metadata-package:{old_key}:renamed:{new_key}")

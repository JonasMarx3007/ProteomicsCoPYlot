from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

import pandas as pd

from app.schemas.annotation import MetadataAnnotationKind
from app.services.dataset_store import get_active_package
from app.services.runtime_cache import invalidate_runtime_cache
from app.services.session_context import get_session_id

DEFAULT_METADATA_PROFILE_NAME = "Metadata"
MAX_MANUAL_METADATA_PROFILES = 5
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
    source_profiles: tuple[str, ...] | None = None


def _empty_metadata_state() -> dict[MetadataAnnotationKind, StoredUploadedMetadata | None]:
    return {
        "protein": None,
        "phospho": None,
    }


@dataclass
class _MetadataSessionState:
    uploaded_metadata_by_package: dict[
        str, dict[str, dict[MetadataAnnotationKind, StoredUploadedMetadata | None]]
    ]
    active_profile_by_package: dict[str, str]
    auto_combined_profiles_by_package: dict[str, set[str]]
    auto_combined_profile_sources_by_package: dict[str, dict[str, tuple[str, ...]]]


def _new_session_state() -> _MetadataSessionState:
    return _MetadataSessionState(
        uploaded_metadata_by_package={},
        active_profile_by_package={},
        auto_combined_profiles_by_package={},
        auto_combined_profile_sources_by_package={},
    )


_METADATA_SESSIONS: dict[str, _MetadataSessionState] = {}


def _session_state() -> _MetadataSessionState:
    session_id = get_session_id()
    state = _METADATA_SESSIONS.get(session_id)
    if state is None:
        state = _new_session_state()
        _METADATA_SESSIONS[session_id] = state
    return state


def _uploaded_metadata_by_package() -> dict[
    str, dict[str, dict[MetadataAnnotationKind, StoredUploadedMetadata | None]]
]:
    return _session_state().uploaded_metadata_by_package


def _active_profile_by_package() -> dict[str, str]:
    return _session_state().active_profile_by_package


def _auto_combined_profiles_by_package() -> dict[str, set[str]]:
    return _session_state().auto_combined_profiles_by_package


def _auto_combined_profile_sources_by_package() -> dict[str, dict[str, tuple[str, ...]]]:
    return _session_state().auto_combined_profile_sources_by_package


def _resolve_package(package_name: str | None) -> str:
    text = str(package_name or "").strip()
    return text or get_active_package()


def _ensure_package(package_name: str | None = None) -> str:
    resolved = _resolve_package(package_name)
    if resolved not in _uploaded_metadata_by_package():
        _uploaded_metadata_by_package()[resolved] = {
            DEFAULT_METADATA_PROFILE_NAME: _empty_metadata_state()
        }
    if resolved not in _auto_combined_profiles_by_package():
        _auto_combined_profiles_by_package()[resolved] = set()
    if resolved not in _auto_combined_profile_sources_by_package():
        _auto_combined_profile_sources_by_package()[resolved] = {}
    if resolved not in _active_profile_by_package():
        _active_profile_by_package()[resolved] = DEFAULT_METADATA_PROFILE_NAME
    if _active_profile_by_package()[resolved] not in _uploaded_metadata_by_package()[resolved]:
        _uploaded_metadata_by_package()[resolved][_active_profile_by_package()[resolved]] = (
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
    return _active_profile_by_package().get(package, DEFAULT_METADATA_PROFILE_NAME)


def _manual_profile_names(package_name: str) -> list[str]:
    package = _ensure_package(package_name)
    profiles = _uploaded_metadata_by_package()[package]
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())
    return [
        name
        for name, state in profiles.items()
        if name not in auto_profiles
        and (
            name != DEFAULT_METADATA_PROFILE_NAME
            or any(stored is not None for stored in state.values())
        )
    ]


def _ensure_manual_profile_capacity(package_name: str, profile_name: str) -> None:
    """Reject a new manual profile without counting generated combinations."""
    package = _ensure_package(package_name)
    name = str(profile_name or "").strip()
    if not name:
        return

    profiles = _uploaded_metadata_by_package()[package]
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())
    if name in profiles and name not in auto_profiles:
        state = profiles[name]
        if name != DEFAULT_METADATA_PROFILE_NAME or any(
            stored is not None for stored in state.values()
        ):
            return
    if len(_manual_profile_names(package)) >= MAX_MANUAL_METADATA_PROFILES:
        raise ValueError(
            "A dataset package can contain at most "
            f"{MAX_MANUAL_METADATA_PROFILES} manual metadata profiles. "
            "Reuse or rename an existing profile."
        )


def _ensure_profile(
    profile_name: str | None = None,
    *,
    package_name: str | None = None,
) -> tuple[str, str]:
    package = _ensure_package(package_name)
    resolved_profile = _normalize_profile_name(profile_name, package)
    profiles = _uploaded_metadata_by_package()[package]
    if resolved_profile not in profiles:
        _ensure_manual_profile_capacity(package, resolved_profile)
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
    return _uploaded_metadata_by_package()[package][resolved_profile]


def _combined_profile_sources(profile_names: list[str]) -> list[tuple[str, ...]]:
    sources: list[tuple[str, ...]] = []
    for size in range(2, len(profile_names) + 1):
        sources.extend(combinations(profile_names, size))
    return sources


def _refresh_combined_profile_keys(package_name: str) -> None:
    package = _ensure_package(package_name)
    profiles = _uploaded_metadata_by_package()[package]
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())
    auto_sources = _auto_combined_profile_sources_by_package().setdefault(package, {})

    manual_profiles = _manual_profile_names(package)
    expected_sources = {
        "-".join(source_profiles): source_profiles
        for source_profiles in _combined_profile_sources(manual_profiles)
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
        if _active_profile_by_package().get(package) == name:
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
    pair_col = column_map.get("pair_id")

    selected_columns = [sample_col, condition_col]
    if pair_col and pair_col not in selected_columns:
        selected_columns.append(pair_col)
    out = normalized[selected_columns].copy()
    rename_map = {sample_col: "sample", condition_col: "condition"}
    if pair_col and pair_col != condition_col:
        rename_map[pair_col] = "pair_id"
    out = out.rename(columns=rename_map)
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
    if "pair_id" in out.columns:
        out["pair_id"] = (
            out["pair_id"].where(pd.notna(out["pair_id"]), "").astype(str).str.strip()
        )
    out = out[(out["sample"] != "") & (out["condition"] != "")]
    if "pair_id" in out.columns and out["sample"].duplicated(keep=False).any():
        duplicates = (
            out.loc[out["sample"].duplicated(keep=False), "sample"]
            .drop_duplicates()
            .tolist()
        )
        raise ValueError(
            "Metadata with pair_id must contain each sample exactly once. "
            f"Duplicates: {', '.join(duplicates)}."
        )
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
        # Fallback for legacy metadata files where the first column stores sample names.
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

    left_condition_order = {
        condition: index
        for index, condition in enumerate(left["condition"].drop_duplicates().astype(str).tolist())
    }
    right_condition_order = {
        condition: index
        for index, condition in enumerate(right["condition"].drop_duplicates().astype(str).tolist())
    }

    left_ordered = left.copy()
    left_ordered["_left_order"] = range(len(left_ordered))
    left_ordered["_left_condition_order"] = (
        left_ordered["condition"].astype(str).map(left_condition_order)
    )

    merged = left_ordered.merge(right, on="sample", how="inner", suffixes=("_left", "_right"))
    if merged.empty:
        return pd.DataFrame(columns=["sample", "condition"])

    merged["condition"] = (
        merged["condition_left"].astype(str).str.strip()
        + "-"
        + merged["condition_right"].astype(str).str.strip()
    )
    merged = merged[(merged["condition"] != "-") & (merged["condition"] != "")]
    pair_columns = [column for column in ("pair_id_left", "pair_id_right", "pair_id") if column in merged]
    if len(pair_columns) == 2:
        left_pairs = merged[pair_columns[0]].astype(str).str.strip()
        right_pairs = merged[pair_columns[1]].astype(str).str.strip()
        conflicts = (left_pairs != "") & (right_pairs != "") & (left_pairs != right_pairs)
        if conflicts.any():
            samples = merged.loc[conflicts, "sample"].astype(str).tolist()
            raise ValueError(
                "Combined metadata profiles contain conflicting pair_id values for: "
                f"{', '.join(samples)}."
            )
        merged["pair_id"] = left_pairs.where(left_pairs != "", right_pairs)
    elif len(pair_columns) == 1 and pair_columns[0] != "pair_id":
        merged["pair_id"] = merged[pair_columns[0]].astype(str).str.strip()
    merged["_right_condition_order"] = (
        merged["condition_right"].astype(str).map(right_condition_order)
    )
    merged = merged.sort_values(
        ["_left_condition_order", "_right_condition_order", "_left_order"],
        kind="stable",
    )
    output_columns = ["sample", "condition"]
    if "pair_id" in merged.columns:
        output_columns.append("pair_id")
    out = merged[output_columns].drop_duplicates(subset=["sample"], keep="first")
    return out.reset_index(drop=True)


def build_combined_metadata_frame(
    *frames: pd.DataFrame,
) -> pd.DataFrame:
    valid_frames = [frame for frame in frames if isinstance(frame, pd.DataFrame)]
    if len(valid_frames) < 2:
        return pd.DataFrame(columns=["sample", "condition"])

    combined = valid_frames[0]
    for frame in valid_frames[1:]:
        combined = _combine_profiles(left_frame=combined, right_frame=frame)
        if combined.empty:
            return combined
    return combined


def _regenerate_combined_profiles(package_name: str, kind: MetadataAnnotationKind) -> None:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    profiles = _uploaded_metadata_by_package()[package]
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())

    # Remove previous auto-generated combined metadata for this kind.
    for profile_name, state in list(profiles.items()):
        stored = state.get(kind)
        if stored is not None and stored.auto_generated:
            state[kind] = None
            if all(value is None for value in state.values()) and profile_name in auto_profiles:
                if _active_profile_by_package().get(package) != profile_name:
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

    manual_map = {profile_name: stored for profile_name, stored in manual_profiles}
    for source_profiles in _combined_profile_sources([name for name, _ in manual_profiles]):
        combined_name = "-".join(source_profiles)
        if combined_name not in profiles:
            profiles[combined_name] = _empty_metadata_state()
            invalidate_runtime_cache(f"metadata:{package}:profile:{combined_name}:created")
        state = profiles.get(combined_name)
        existing = state.get(kind) if state is not None else None
        if existing is not None and not existing.auto_generated:
            # Respect user-managed profile if it already exists with same name.
            continue

        source_frames = [manual_map[name].frame for name in source_profiles]
        combined_frame = build_combined_metadata_frame(*source_frames)
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
            source_profiles=source_profiles,
        )
        auto_profiles.add(combined_name)
        invalidate_runtime_cache(f"metadata:{package}:{combined_name}:{kind}:autogenerated")


def get_active_profile(*, package_name: str | None = None) -> str:
    package = _ensure_package(package_name)
    return _active_profile_by_package().get(package, DEFAULT_METADATA_PROFILE_NAME)


def list_profiles(*, package_name: str | None = None) -> list[str]:
    package = _ensure_package(package_name)
    active = get_active_profile(package_name=package)
    names = list(_uploaded_metadata_by_package()[package].keys())
    # Hide empty legacy default profile once custom profiles exist.
    if DEFAULT_METADATA_PROFILE_NAME in names and len(names) > 1:
        state = _uploaded_metadata_by_package()[package][DEFAULT_METADATA_PROFILE_NAME]
        if all(value is None for value in state.values()) and active != DEFAULT_METADATA_PROFILE_NAME:
            names = [name for name in names if name != DEFAULT_METADATA_PROFILE_NAME]
    if active in names:
        return [active] + [name for name in names if name != active]
    return names


def list_auto_generated_profiles(*, package_name: str | None = None) -> list[str]:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    profiles = set(_uploaded_metadata_by_package()[package].keys())
    auto = _auto_combined_profiles_by_package().get(package, set())
    names = sorted((profiles & auto), key=lambda value: value.lower())
    return names


def get_auto_generated_profile_sources(
    profile_name: str,
    *,
    package_name: str | None = None,
) -> tuple[str, ...] | None:
    package = _ensure_package(package_name)
    _refresh_combined_profile_keys(package)
    key = str(profile_name or "").strip()
    if not key:
        return None
    sources = _auto_combined_profile_sources_by_package().get(package, {})
    return sources.get(key)


def set_active_profile(profile_name: str, *, package_name: str | None = None) -> str:
    package = _ensure_package(package_name)
    resolved_profile = str(profile_name or "").strip()
    if not resolved_profile:
        raise ValueError("Metadata profile name must not be empty.")
    profiles = _uploaded_metadata_by_package()[package]
    if resolved_profile not in profiles:
        raise ValueError(f"Metadata profile '{resolved_profile}' does not exist.")
    _active_profile_by_package()[package] = resolved_profile
    invalidate_runtime_cache(f"metadata:{package}:profile:{resolved_profile}:active")
    return resolved_profile


def create_profile(profile_name: str, *, package_name: str | None = None) -> str:
    name = str(profile_name or "").strip()
    if not name:
        raise ValueError("Metadata profile name must not be empty.")
    package = _ensure_package(package_name)
    profiles = _uploaded_metadata_by_package()[package]
    if name in profiles:
        raise ValueError(f"Metadata profile '{name}' already exists.")
    _ensure_manual_profile_capacity(package, name)
    profiles[name] = _empty_metadata_state()
    _auto_combined_profiles_by_package().setdefault(package, set()).discard(name)
    _refresh_combined_profile_keys(package)
    _active_profile_by_package()[package] = name
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
    profiles = _uploaded_metadata_by_package()[package]
    if old_key not in profiles:
        raise ValueError(f"Metadata profile '{old_key}' does not exist.")
    if new_key in profiles and new_key != old_key:
        raise ValueError(f"Metadata profile '{new_key}' already exists.")
    if old_key == new_key:
        return old_key

    profiles[new_key] = profiles.pop(old_key)
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())
    if old_key in auto_profiles:
        auto_profiles.discard(old_key)
        auto_profiles.add(new_key)
    _refresh_combined_profile_keys(package)
    if _active_profile_by_package().get(package) == old_key:
        _active_profile_by_package()[package] = new_key
    _regenerate_combined_profiles(package, "protein")
    _regenerate_combined_profiles(package, "phospho")
    invalidate_runtime_cache(f"metadata:{package}:profile:{old_key}:renamed:{new_key}")
    return new_key


def delete_profile(
    profile_name: str,
    *,
    package_name: str | None = None,
) -> list[str]:
    """Delete one manual profile and every generated profile that depends on it."""
    package = _ensure_package(package_name)
    name = str(profile_name or "").strip()
    if not name:
        raise ValueError("Metadata profile name must not be empty.")

    profiles = _uploaded_metadata_by_package()[package]
    if name not in profiles:
        raise ValueError(f"Metadata profile '{name}' does not exist.")
    auto_profiles = _auto_combined_profiles_by_package().setdefault(package, set())
    auto_sources = _auto_combined_profile_sources_by_package().setdefault(package, {})
    if name in auto_profiles:
        raise ValueError(
            f"Metadata profile '{name}' is generated automatically. "
            "Delete one of its source profiles instead."
        )

    dependent_profiles = {
        generated_name
        for generated_name, source_names in auto_sources.items()
        if name in source_names
    }
    removed_profiles = [name, *sorted(dependent_profiles, key=str.lower)]
    for generated_name in dependent_profiles:
        profiles.pop(generated_name, None)
        auto_profiles.discard(generated_name)
        auto_sources.pop(generated_name, None)

    if name == DEFAULT_METADATA_PROFILE_NAME:
        profiles[name] = _empty_metadata_state()
    else:
        profiles.pop(name, None)
    auto_profiles.discard(name)
    auto_sources.pop(name, None)

    active = _active_profile_by_package().get(package, DEFAULT_METADATA_PROFILE_NAME)
    if active in removed_profiles:
        # Make the active key valid before calling helpers that ensure package
        # invariants; otherwise they would recreate the just-deleted active
        # profile as an empty manual profile.
        profiles.setdefault(DEFAULT_METADATA_PROFILE_NAME, _empty_metadata_state())
        _active_profile_by_package()[package] = DEFAULT_METADATA_PROFILE_NAME
        remaining_manual = [
            profile
            for profile, state in profiles.items()
            if profile not in auto_profiles
            and (
                profile != DEFAULT_METADATA_PROFILE_NAME
                or any(stored is not None for stored in state.values())
            )
        ]
        fallback = (
            remaining_manual[0]
            if remaining_manual
            else DEFAULT_METADATA_PROFILE_NAME
        )
        _active_profile_by_package()[package] = fallback

    _refresh_combined_profile_keys(package)
    _regenerate_combined_profiles(package, "protein")
    _regenerate_combined_profiles(package, "phospho")
    invalidate_runtime_cache(f"metadata:{package}:profile:{name}:deleted")
    return removed_profiles


def save_uploaded_metadata(
    kind: MetadataAnnotationKind,
    filename: str,
    frame: pd.DataFrame,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
) -> StoredUploadedMetadata:
    package = _ensure_package(package_name)
    profile = _normalize_profile_name(profile_name, package)
    return save_uploaded_metadata_profiles(
        kind,
        filename,
        [(profile, frame)],
        package_name=package,
    )


def save_uploaded_metadata_profiles(
    kind: MetadataAnnotationKind,
    filename: str,
    profile_frames: list[tuple[str, pd.DataFrame]],
    *,
    package_name: str | None = None,
    active_profile_name: str | None = None,
) -> StoredUploadedMetadata:
    """Atomically save one upload as one or more manual source profiles."""
    if not profile_frames:
        raise ValueError("Metadata upload did not produce any profiles.")

    normalized_frames: list[tuple[str, pd.DataFrame]] = []
    seen_names: set[str] = set()
    for raw_name, frame in profile_frames:
        name = str(raw_name or "").strip()
        if not name:
            raise ValueError("Metadata profile name must not be empty.")
        if name in seen_names:
            raise ValueError(f"Metadata profile '{name}' occurs more than once in the upload.")
        if not isinstance(frame, pd.DataFrame):
            raise ValueError(f"Metadata profile '{name}' is not a table.")
        seen_names.add(name)
        normalized_frames.append((name, frame))

    package = _ensure_package(package_name)
    prospective_manual_profiles = set(_manual_profile_names(package))
    prospective_manual_profiles.update(name for name, _ in normalized_frames)
    if len(prospective_manual_profiles) > MAX_MANUAL_METADATA_PROFILES:
        raise ValueError(
            "This upload would create "
            f"{len(prospective_manual_profiles)} manual metadata profiles, above the "
            f"limit. A dataset package can contain at most "
            f"{MAX_MANUAL_METADATA_PROFILES} manual metadata profiles. Reuse existing "
            "profile names or remove grouping columns from the upload."
        )

    profiles_by_package = _uploaded_metadata_by_package()
    auto_by_package = _auto_combined_profiles_by_package()
    sources_by_package = _auto_combined_profile_sources_by_package()
    active_by_package = _active_profile_by_package()
    # The transaction only replaces per-kind state entries; StoredUploadedMetadata
    # objects and their potentially large DataFrames are immutable here. Copy the
    # small dictionaries without duplicating every uploaded table in memory.
    profiles_snapshot = {
        name: state.copy()
        for name, state in profiles_by_package[package].items()
    }
    auto_snapshot = set(auto_by_package[package])
    sources_snapshot = dict(sources_by_package[package])
    active_snapshot = active_by_package[package]

    stored_by_name: dict[str, StoredUploadedMetadata] = {}
    try:
        profiles = profiles_by_package[package]
        auto_profiles = auto_by_package[package]
        auto_sources = sources_by_package[package]
        created_at = datetime.now(timezone.utc).isoformat()
        for name, frame in normalized_frames:
            if name not in profiles:
                profiles[name] = _empty_metadata_state()
                invalidate_runtime_cache(f"metadata:{package}:profile:{name}:created")
            auto_profiles.discard(name)
            auto_sources.pop(name, None)
            stored = StoredUploadedMetadata(
                kind=kind,
                filename=filename,
                frame=frame.copy(),
                created_at=created_at,
                auto_generated=False,
                source_profiles=None,
            )
            profiles[name][kind] = stored
            stored_by_name[name] = stored
            invalidate_runtime_cache(f"metadata:{package}:{name}:{kind}:uploaded")

        selected_profile = str(active_profile_name or "").strip()
        if selected_profile:
            if selected_profile not in stored_by_name:
                raise ValueError(
                    f"Active metadata profile '{selected_profile}' is not part of the upload."
                )
            active_by_package[package] = selected_profile
        _refresh_combined_profile_keys(package)
        _regenerate_combined_profiles(package, kind)
        return stored_by_name[selected_profile or normalized_frames[0][0]]
    except Exception:
        profiles_by_package[package] = profiles_snapshot
        auto_by_package[package] = auto_snapshot
        sources_by_package[package] = sources_snapshot
        active_by_package[package] = active_snapshot
        invalidate_runtime_cache(f"metadata:{package}:profile-upload-rolled-back")
        raise


def get_uploaded_metadata(
    kind: MetadataAnnotationKind,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
) -> StoredUploadedMetadata | None:
    state = _profile_state(profile_name=profile_name, package_name=package_name)
    return state.get(kind)


def _frame_with_pair_ids(
    frame: pd.DataFrame,
    pair_ids_by_sample: dict[str, str],
) -> pd.DataFrame:
    updated = frame.copy()
    column_map = {str(column).strip().lower(): column for column in updated.columns}
    sample_col = next(
        (column_map[alias] for alias in SAMPLE_COLUMN_ALIASES if alias in column_map),
        updated.columns[0] if len(updated.columns) >= 2 else None,
    )
    if sample_col is None:
        return updated

    pair_col = column_map.get("pair_id", "pair_id")
    if pair_col not in updated.columns:
        updated[pair_col] = ""
    normalized_samples = (
        updated[sample_col]
        .where(pd.notna(updated[sample_col]), "")
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )
    mapped_pair_ids = normalized_samples.map(pair_ids_by_sample)
    matched = mapped_pair_ids.notna()
    updated.loc[matched, pair_col] = mapped_pair_ids.loc[matched].astype(str)
    return updated


def update_uploaded_metadata_pair_ids(
    kind: MetadataAnnotationKind,
    pair_ids_by_sample: dict[str, str],
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
) -> bool:
    resolved_package = _ensure_package(package_name)
    resolved_profile = _normalize_profile_name(profile_name, resolved_package)
    state = _profile_state(
        profile_name=resolved_profile,
        package_name=resolved_package,
    )
    active_stored = state.get(kind)
    if active_stored is None:
        return False

    target_profiles = (
        active_stored.source_profiles
        if active_stored.auto_generated and active_stored.source_profiles
        else (resolved_profile,)
    )
    changed = False
    for target_profile in target_profiles:
        target_state = _profile_state(
            profile_name=target_profile,
            package_name=resolved_package,
        )
        target_stored = target_state.get(kind)
        if target_stored is None:
            continue
        updated_frame = _frame_with_pair_ids(target_stored.frame, pair_ids_by_sample)
        if updated_frame.equals(target_stored.frame):
            continue
        target_stored.frame = updated_frame
        changed = True
        invalidate_runtime_cache(
            f"metadata:{resolved_package}:{target_profile}:{kind}:pairing-updated"
        )

    if changed:
        _regenerate_combined_profiles(resolved_package, kind)
    return changed


def clear_uploaded_metadata(
    kind: MetadataAnnotationKind,
    *,
    package_name: str | None = None,
    profile_name: str | None = None,
    clear_all_profiles: bool = False,
) -> None:
    resolved_package = _ensure_package(package_name)
    profiles = _uploaded_metadata_by_package()[resolved_package]
    auto_profiles = _auto_combined_profiles_by_package().setdefault(resolved_package, set())
    if clear_all_profiles:
        for profile, state in list(profiles.items()):
            state[kind] = None
            invalidate_runtime_cache(f"metadata:{resolved_package}:{profile}:{kind}:cleared")
            if all(value is None for value in state.values()) and profile in auto_profiles:
                if _active_profile_by_package().get(resolved_package) != profile:
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
    if old_key not in _uploaded_metadata_by_package():
        return
    if new_key in _uploaded_metadata_by_package():
        raise ValueError(f"Metadata package '{new_key}' already exists.")
    _uploaded_metadata_by_package()[new_key] = _uploaded_metadata_by_package().pop(old_key)
    if old_key in _active_profile_by_package():
        _active_profile_by_package()[new_key] = _active_profile_by_package().pop(old_key)
    if old_key in _auto_combined_profiles_by_package():
        _auto_combined_profiles_by_package()[new_key] = _auto_combined_profiles_by_package().pop(old_key)
    if old_key in _auto_combined_profile_sources_by_package():
        _auto_combined_profile_sources_by_package()[new_key] = _auto_combined_profile_sources_by_package().pop(
            old_key
        )
    invalidate_runtime_cache(f"metadata-package:{old_key}:renamed:{new_key}")


def reset_all_uploaded_metadata(*, all_sessions: bool = False) -> None:
    if all_sessions:
        _METADATA_SESSIONS.clear()
    else:
        _METADATA_SESSIONS.pop(get_session_id(), None)
    invalidate_runtime_cache("metadata:reset-all", all_sessions=all_sessions)


def snapshot_metadata_session_state() -> _MetadataSessionState | None:
    """Detach-safe reference used before the session entry is atomically replaced."""
    return _METADATA_SESSIONS.get(get_session_id())


def restore_metadata_session_state(snapshot: _MetadataSessionState | None) -> None:
    session_id = get_session_id()
    if snapshot is None:
        _METADATA_SESSIONS.pop(session_id, None)
    else:
        _METADATA_SESSIONS[session_id] = snapshot
    invalidate_runtime_cache("metadata:transaction-restored")


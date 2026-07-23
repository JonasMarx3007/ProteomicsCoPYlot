from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re

import numpy as np
import pandas as pd

from app.schemas.annotation import ConditionAssignment, FilterMode
from app.services.functions import (
    build_metadata_from_conditions,
    filter_data,
    log2_transform_data,
    use_existing_log2_data,
)

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
class AnnotationComputationResult:
    metadata: pd.DataFrame
    log2_data: pd.DataFrame
    filtered_data: pd.DataFrame
    is_log2_transformed: bool
    log2_auto_detected: bool
    auto_detected: bool
    warnings: list[str]


@dataclass(frozen=True)
class Log2ScaleDetection:
    is_log2_transformed: bool | None
    reason: str


def detect_log2_transformed(
    data: pd.DataFrame,
    sample_columns: list[str],
) -> Log2ScaleDetection:
    """Classify scale using only confirmed measurement/sample columns."""
    selected_columns = [str(column) for column in sample_columns if str(column) in data.columns]
    if not selected_columns:
        return Log2ScaleDetection(None, "no matching sample columns were available")

    explicit_log2 = [column for column in selected_columns if "log2" in column.lower()]
    if explicit_log2:
        return Log2ScaleDetection(
            True,
            f"{len(explicit_log2)} selected sample column name(s) explicitly indicate log2 values",
        )

    numeric = data[selected_columns].apply(pd.to_numeric, errors="coerce")
    usable: list[np.ndarray] = []
    for column in selected_columns:
        values = numeric[column].to_numpy(dtype=float, copy=False)
        finite = values[np.isfinite(values)]
        if finite.size >= 3:
            usable.append(finite)

    if not usable:
        return Log2ScaleDetection(None, "the selected sample columns contain no usable numeric values")

    combined = np.concatenate(usable)
    negative_fraction = float(np.mean(combined < 0))
    if negative_fraction >= 0.001:
        return Log2ScaleDetection(
            True,
            "selected sample values include a reproducible negative-value signal",
        )

    q01, q99 = np.nanquantile(combined, [0.01, 0.99])
    if q01 >= 0 and q99 <= 2:
        return Log2ScaleDetection(
            None,
            "non-negative values are confined to 0-2, which can represent either ratios or transformed data",
        )

    log2_votes = 0
    linear_votes = 0
    for finite in usable:
        q50, q95, column_q99 = np.nanquantile(finite, [0.50, 0.95, 0.99])
        if q95 > 50 or column_q99 > 100:
            linear_votes += 1
        elif q50 <= 35 and q95 <= 45 and column_q99 <= 60:
            log2_votes += 1

    required_votes = max(1, (len(usable) + 1) // 2)
    if log2_votes >= required_votes and log2_votes > linear_votes:
        return Log2ScaleDetection(
            True,
            f"{log2_votes} of {len(usable)} selected sample columns have a log2-like value range",
        )
    if linear_votes >= required_votes and linear_votes > log2_votes:
        return Log2ScaleDetection(
            False,
            f"{linear_votes} of {len(usable)} selected sample columns have a linear-intensity value range",
        )
    return Log2ScaleDetection(
        None,
        "the selected sample columns do not provide a consistent scale signal",
    )


def resolve_log2_state(
    data: pd.DataFrame,
    sample_columns: list[str],
    requested_state: bool | None,
) -> tuple[bool, bool, str | None]:
    if requested_state is not None:
        return bool(requested_state), False, None

    detection = detect_log2_transformed(data, sample_columns)
    if detection.is_log2_transformed is None:
        raise ValueError(
            "Could not reliably auto-detect whether the selected sample columns are log2 "
            f"transformed: {detection.reason}. Choose an explicit log2 scale setting."
        )
    scale_label = "already log2 transformed" if detection.is_log2_transformed else "linear"
    warning = (
        f"Sample scale was auto-detected as {scale_label} from {len(sample_columns)} "
        f"selected sample column(s): {detection.reason}."
    )
    return detection.is_log2_transformed, True, warning


def normalize_uploaded_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    if metadata.empty:
        raise ValueError("Uploaded metadata is empty.")

    normalized = metadata.copy()
    normalized.columns = [str(c).strip() for c in normalized.columns]
    column_map = {str(c).strip().lower(): str(c).strip() for c in normalized.columns}

    sample_col = _resolve_sample_column(column_map, normalized.columns)
    if sample_col is None:
        raise ValueError(
            "Uploaded metadata must contain a sample column (e.g. 'sample' or 'data_column_name')."
        )
    sample_key = str(sample_col).strip().lower()
    non_sample_columns = [
        column for column in normalized.columns if str(column).strip().lower() != sample_key
    ]
    if not non_sample_columns:
        raise ValueError(
            "Uploaded metadata must contain at least one grouping column besides 'sample'."
        )

    has_explicit_condition = "condition" in column_map
    condition_col = column_map.get("condition", non_sample_columns[0])
    selected = normalized[[sample_col, *non_sample_columns]].copy()

    alias_map: dict[str, str] = {}
    used_aliases: set[str] = {"sample"}
    for original in non_sample_columns:
        alias = _make_unique_column_alias(str(original), used_aliases)
        alias_map[str(original)] = alias
        used_aliases.add(alias)

    selected = selected.rename(columns={sample_col: "sample", **alias_map})
    condition_alias = alias_map[str(condition_col)]
    if condition_alias != "condition":
        selected.insert(1, "condition", selected[condition_alias])

    cleaned = selected.copy()
    cleaned["sample"] = _clean_string_series(cleaned["sample"]).apply(
        lambda value: re.sub(r"\.0$", "", value)
    )
    for column in cleaned.columns:
        if column == "sample":
            continue
        cleaned[column] = _clean_string_series(cleaned[column])

    cleaned = cleaned[(cleaned["sample"] != "") & (cleaned["condition"] != "")]

    data_columns = set(str(c) for c in data.columns)
    cleaned = cleaned[cleaned["sample"].isin(data_columns)]
    cleaned = cleaned.drop_duplicates(subset=["sample"], keep="first").reset_index(drop=True)
    if cleaned.empty:
        raise ValueError(
            "Uploaded metadata does not match any sample columns in the current dataset."
        )
    cleaned = _append_combined_subset_columns(cleaned)

    # If no explicit "condition" was provided but multiple grouping columns exist,
    # default condition to the mixed first-two-column grouping (e.g. organ-gender).
    if not has_explicit_condition and len(non_sample_columns) >= 2:
        first_alias = alias_map[str(non_sample_columns[0])]
        second_alias = alias_map[str(non_sample_columns[1])]
        mixed_name = f"{first_alias}-{second_alias}"
        if mixed_name in cleaned.columns:
            mixed_values = _clean_string_series(cleaned[mixed_name])
            if (mixed_values != "").all():
                cleaned["condition"] = mixed_values

    return cleaned


def _clean_string_series(series: pd.Series) -> pd.Series:
    return series.where(pd.notna(series), "").astype(str).str.strip()


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


def _make_unique_column_alias(raw_name: str, used_aliases: set[str]) -> str:
    alias = re.sub(r"\s+", "_", raw_name.strip())
    alias = re.sub(r"[^A-Za-z0-9_\-]", "", alias)
    alias = alias.strip("_-")
    if not alias:
        alias = "Metadata"

    candidate = alias
    index = 2
    lowered = {value.lower() for value in used_aliases}
    while candidate.lower() in lowered:
        candidate = f"{alias}_{index}"
        index += 1
    return candidate


def _append_combined_subset_columns(metadata: pd.DataFrame) -> pd.DataFrame:
    if metadata.empty:
        return metadata

    out = metadata.copy()
    subset_columns = [column for column in out.columns if column != "sample"]
    # Keep "condition" available for combinations, but place it after explicit
    # user-provided grouping columns so names like "cells-stimulated" are preferred.
    if "condition" in subset_columns:
        subset_columns = [
            column for column in subset_columns if column != "condition"
        ] + ["condition"]
    if len(subset_columns) < 2:
        return out

    def _combine_columns(columns: tuple[str, ...]) -> pd.Series:
        def _combine_row(row: pd.Series) -> str:
            values = [str(row[column]).strip() for column in columns]
            if any(not value for value in values):
                return ""
            return "-".join(values)

        return out.apply(_combine_row, axis=1)

    for size in range(2, len(subset_columns) + 1):
        for selected in combinations(subset_columns, size):
            forward_name = "-".join(selected)
            if forward_name not in out.columns:
                out[forward_name] = _combine_columns(selected)

            reverse = tuple(reversed(selected))
            reverse_name = "-".join(reverse)
            if reverse_name not in out.columns:
                out[reverse_name] = _combine_columns(reverse)
    return out


def compute_annotation(
    data: pd.DataFrame,
    conditions: list[ConditionAssignment],
    is_log2_transformed: bool | None,
    min_present: int,
    filter_mode: FilterMode,
) -> AnnotationComputationResult:
    metadata_result = build_metadata_from_conditions(
        data,
        [{"name": c.name, "columns": c.columns} for c in conditions],
    )
    metadata = metadata_result.metadata
    auto_detected = metadata_result.auto_detected
    sample_columns = metadata["sample"].tolist()

    if not sample_columns:
        raise ValueError("No sample columns could be determined for metadata.")

    resolved_log2, log2_auto_detected, log2_warning = resolve_log2_state(
        data,
        sample_columns,
        is_log2_transformed,
    )

    if resolved_log2:
        log2_data = use_existing_log2_data(data, sample_columns)
    else:
        log2_data = log2_transform_data(data, sample_columns)

    filtered_data = filter_data(log2_data, metadata, min_present=min_present, mode=filter_mode)

    warnings: list[str] = []
    if log2_warning:
        warnings.append(log2_warning)
    if auto_detected:
        warnings.append("Metadata was auto-generated from date-like column names.")

    return AnnotationComputationResult(
        metadata=metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=resolved_log2,
        log2_auto_detected=log2_auto_detected,
        auto_detected=auto_detected,
        warnings=warnings,
    )


def compute_annotation_from_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    is_log2_transformed: bool | None,
    min_present: int,
    filter_mode: FilterMode,
) -> AnnotationComputationResult:
    normalized_metadata = normalize_uploaded_metadata(data=data, metadata=metadata)
    sample_columns = normalized_metadata["sample"].tolist()
    if not sample_columns:
        raise ValueError("No valid sample columns found in uploaded metadata.")

    resolved_log2, log2_auto_detected, log2_warning = resolve_log2_state(
        data,
        sample_columns,
        is_log2_transformed,
    )

    if resolved_log2:
        log2_data = use_existing_log2_data(data, sample_columns)
    else:
        log2_data = log2_transform_data(data, sample_columns)

    filtered_data = filter_data(
        log2_data,
        normalized_metadata,
        min_present=min_present,
        mode=filter_mode,
    )

    warnings = ["Using uploaded metadata table for annotation."]
    if log2_warning:
        warnings.append(log2_warning)

    return AnnotationComputationResult(
        metadata=normalized_metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        is_log2_transformed=resolved_log2,
        log2_auto_detected=log2_auto_detected,
        auto_detected=False,
        warnings=warnings,
    )

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import re

from app.schemas.annotation import ConditionAssignment, FilterMode
from app.services.functions import (
    build_metadata_from_conditions,
    filter_data,
    log2_transform_data,
    use_existing_log2_data,
)


@dataclass
class AnnotationComputationResult:
    metadata: pd.DataFrame
    log2_data: pd.DataFrame
    filtered_data: pd.DataFrame
    auto_detected: bool
    warnings: list[str]


def normalize_uploaded_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    if metadata.empty:
        raise ValueError("Uploaded metadata is empty.")

    normalized = metadata.copy()
    normalized.columns = [str(c).strip() for c in normalized.columns]
    column_map = {str(c).strip().lower(): str(c).strip() for c in normalized.columns}

    if "sample" not in column_map or "condition" not in column_map:
        raise ValueError("Uploaded metadata must contain 'sample' and 'condition' columns.")

    sample_col = column_map["sample"]
    condition_col = column_map["condition"]
    cleaned = normalized[[sample_col, condition_col]].copy()
    cleaned.columns = ["sample", "condition"]
    cleaned["sample"] = cleaned["sample"].astype(str).str.strip()
    cleaned["sample"] = cleaned["sample"].apply(
        lambda value: re.sub(r"\.0$", "", value)
    )
    cleaned["condition"] = cleaned["condition"].astype(str).str.strip()
    cleaned = cleaned[(cleaned["sample"] != "") & (cleaned["condition"] != "")]

    data_columns = set(str(c) for c in data.columns)
    cleaned = cleaned[cleaned["sample"].isin(data_columns)]
    cleaned = cleaned.drop_duplicates(subset=["sample"], keep="first").reset_index(drop=True)
    if cleaned.empty:
        raise ValueError(
            "Uploaded metadata does not match any sample columns in the current dataset."
        )
    return cleaned


def compute_annotation(
    data: pd.DataFrame,
    conditions: list[ConditionAssignment],
    is_log2_transformed: bool,
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

    if is_log2_transformed:
        log2_data = use_existing_log2_data(data, sample_columns)
    else:
        log2_data = log2_transform_data(data, sample_columns)

    filtered_data = filter_data(log2_data, metadata, min_present=min_present, mode=filter_mode)

    warnings: list[str] = []
    if auto_detected:
        warnings.append("Metadata was auto-generated from date-like column names.")

    return AnnotationComputationResult(
        metadata=metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        auto_detected=auto_detected,
        warnings=warnings,
    )


def compute_annotation_from_metadata(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    is_log2_transformed: bool,
    min_present: int,
    filter_mode: FilterMode,
) -> AnnotationComputationResult:
    normalized_metadata = normalize_uploaded_metadata(data=data, metadata=metadata)
    sample_columns = normalized_metadata["sample"].tolist()
    if not sample_columns:
        raise ValueError("No valid sample columns found in uploaded metadata.")

    if is_log2_transformed:
        log2_data = use_existing_log2_data(data, sample_columns)
    else:
        log2_data = log2_transform_data(data, sample_columns)

    filtered_data = filter_data(
        log2_data,
        normalized_metadata,
        min_present=min_present,
        mode=filter_mode,
    )

    return AnnotationComputationResult(
        metadata=normalized_metadata,
        log2_data=log2_data,
        filtered_data=filtered_data,
        auto_detected=False,
        warnings=["Using uploaded metadata table for annotation."],
    )

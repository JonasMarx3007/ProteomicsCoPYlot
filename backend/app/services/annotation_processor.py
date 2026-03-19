from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

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

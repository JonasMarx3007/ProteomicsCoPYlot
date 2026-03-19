from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from app.schemas.annotation import AnnotationFilterConfig, AnnotationKind


@dataclass
class StoredAnnotation:
    kind: AnnotationKind
    source_data: pd.DataFrame
    metadata: pd.DataFrame
    log2_data: pd.DataFrame
    filtered_data: pd.DataFrame
    is_log2_transformed: bool
    filter_config: AnnotationFilterConfig
    auto_detected: bool
    warnings: list[str]
    created_at: str


_ANNOTATIONS: dict[AnnotationKind, StoredAnnotation | None] = {
    "protein": None,
    "phospho": None,
}


def save_annotation(
    kind: AnnotationKind,
    source_data: pd.DataFrame,
    metadata: pd.DataFrame,
    log2_data: pd.DataFrame,
    filtered_data: pd.DataFrame,
    is_log2_transformed: bool,
    filter_config: AnnotationFilterConfig,
    auto_detected: bool,
    warnings: list[str],
) -> StoredAnnotation:
    stored = StoredAnnotation(
        kind=kind,
        source_data=source_data.copy(),
        metadata=metadata.copy(),
        log2_data=log2_data.copy(),
        filtered_data=filtered_data.copy(),
        is_log2_transformed=is_log2_transformed,
        filter_config=filter_config,
        auto_detected=auto_detected,
        warnings=list(warnings),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _ANNOTATIONS[kind] = stored
    return stored


def get_annotation(kind: AnnotationKind) -> StoredAnnotation | None:
    return _ANNOTATIONS.get(kind)


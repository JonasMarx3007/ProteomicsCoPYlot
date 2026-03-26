from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import DataSource, HistogramBin
from app.schemas.qc import BoxplotPoint, QcSummaryResponse, SampleMetricPoint
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.functions import choose_best_source, histogram
from app.services.runtime_cache import apply_cached_wrappers


def _best_qc_source(kind: AnnotationKind) -> tuple[DataSource, pd.DataFrame, list[str]]:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    filtered = annotation.filtered_data if annotation is not None else None
    log2 = annotation.log2_data if annotation is not None else None
    source, frame = choose_best_source(filtered, log2, raw)
    warnings: list[str] = []
    if source == "raw":
        warnings.append("Using raw data because filtered/log2 data is unavailable.")
    return source, frame, warnings


def qc_summary(kind: AnnotationKind) -> QcSummaryResponse:
    source_used, frame, warnings = _best_qc_source(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    row_count = max(1, len(numeric))

    coverage = [
        SampleMetricPoint(sample=col, value=float((numeric[col].notna().sum() / row_count) * 100.0))
        for col in sample_columns
    ]

    all_values = numeric.values.flatten()
    intensity_hist = [
        HistogramBin(start=start, end=end, count=count)
        for start, end, count in histogram(all_values, bins=40)
    ]

    boxplot_points: list[BoxplotPoint] = []
    cv_points: list[SampleMetricPoint] = []
    for col in sample_columns:
        values = numeric[col].dropna().values.astype(float)
        if values.size == 0:
            continue

        q1, median, q3 = np.percentile(values, [25, 50, 75])
        boxplot_points.append(
            BoxplotPoint(
                sample=col,
                min=float(np.min(values)),
                q1=float(q1),
                median=float(median),
                q3=float(q3),
                max=float(np.max(values)),
            )
        )

        mean = float(np.mean(values))
        std = float(np.std(values))
        cv = float((std / mean) * 100.0) if mean != 0 else 0.0
        cv_points.append(SampleMetricPoint(sample=col, value=cv))

    return QcSummaryResponse(
        kind=kind,
        sourceUsed=source_used,
        sampleColumns=sample_columns,
        coverage=coverage,
        intensityHistogram=intensity_hist,
        boxplot=boxplot_points,
        cv=cv_points,
        warnings=warnings,
    )


apply_cached_wrappers(globals(), ["qc_summary"])

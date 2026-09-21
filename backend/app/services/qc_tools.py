from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import HistogramBin
from app.schemas.qc import BoxplotPoint, ConditionCvPoint, QcSummaryResponse, SampleMetricPoint
from app.services.data_tools import _get_sample_columns
from app.services.functions import histogram, qc_matrix
from app.services.table_functions import qc_cv_table
from app.services.runtime_cache import apply_cached_wrappers


def qc_summary(kind: AnnotationKind) -> QcSummaryResponse:
    # QC describes the data as loaded. This endpoint used to summarise the
    # FILTERED matrix while the coverage and boxplot tables summarised the
    # unfiltered one, so the same sample reported 7,404 here and 7,410 there.
    frame, _ = qc_matrix(kind)
    source_used, warnings = "data", []
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

    # Delegate to the same computation the CV plot and CV table use, rather than
    # keeping a third definition here. The previous local version divided the
    # standard deviation by the mean *across features within one sample*, on
    # log2 values -- which is not a coefficient of variation: a CV needs
    # replicates to vary across, and is only meaningful on a linear scale.
    cv_frame = qc_cv_table(kind)
    cv_points = [
        ConditionCvPoint(
            condition=str(row["Condition"]),
            mean=float(row["mean"]),
            median=float(row["median"]),
            q1=float(row["Q1"]),
            q3=float(row["Q3"]),
            lowerWhisker=float(row["lower_whisker"]),
            upperWhisker=float(row["upper_whisker"]),
        )
        for _, row in cv_frame.iterrows()
    ] if not cv_frame.empty else []

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

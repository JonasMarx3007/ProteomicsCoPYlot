from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import (
    ConditionPaletteResponse,
    ConditionPaletteUpdateRequest,
    ComparativeHistogramBin,
    CurvePoint,
    DataSource,
    DistributionSummaryResponse,
    IdTranslationRequest,
    IdTranslationResponse,
    DuplicateFrequencyPoint,
    FirstDigitPoint,
    HistogramBin,
    ImputationResultResponse,
    ImputationRunRequest,
    QQPoint,
    ValueDistributionStats,
    VerificationSummaryResponse,
)
from app.services.annotation_store import get_annotation
from app.services.condition_palette_store import get_condition_palette
from app.services.condition_palette_store import set_condition_palette
from app.services.dataset_store import get_current_dataset
from app.services.id_translation import export_id_translation as export_id_translation_service
from app.services.id_translation import run_id_translation as run_id_translation_service
from app.services.functions import (
    choose_best_source,
    comparative_histogram,
    data_pattern_structure_data,
    first_digit_distribution_data,
    histogram,
    impute_values_with_diagnostics,
    inverse_log2_transform_data,
    normal_fit_curve,
    qqnorm_plot_data,
)


def _preview(df: pd.DataFrame, rows: int = 20) -> list[dict[str, object]]:
    return df.head(rows).where(pd.notna(df.head(rows)), None).to_dict(orient="records")


def _get_current_frame(kind: AnnotationKind) -> pd.DataFrame:
    current = get_current_dataset(kind)
    if current is None or not hasattr(current, "frame"):
        raise ValueError(f"No {kind} dataset is currently loaded.")
    return current.frame.copy()


def _get_sample_columns(kind: AnnotationKind, frame: pd.DataFrame) -> list[str]:
    annotation = get_annotation(kind)
    if annotation is not None:
        cols = [c for c in annotation.metadata["sample"].tolist() if c in frame.columns]
        if cols:
            return cols
    return frame.select_dtypes(include=[np.number]).columns.astype(str).tolist()


def _verification_frame(kind: AnnotationKind) -> tuple[pd.DataFrame, list[str]]:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is None:
        return raw, _get_sample_columns(kind, raw)

    sample_columns = [c for c in annotation.metadata["sample"].tolist() if c in annotation.log2_data.columns]
    if not sample_columns:
        return raw, _get_sample_columns(kind, raw)

    if annotation.is_log2_transformed:
        org = inverse_log2_transform_data(annotation.log2_data, sample_columns)
    else:
        org = annotation.source_data.copy()

    return org, [c for c in sample_columns if c in org.columns]


def _best_imputation_source(kind: AnnotationKind) -> tuple[DataSource, pd.DataFrame, list[str]]:
    raw_frame = _get_current_frame(kind)
    annotation = get_annotation(kind)
    filtered = annotation.filtered_data if annotation is not None else None
    log2 = annotation.log2_data if annotation is not None else None
    source, frame = choose_best_source(filtered, log2, raw_frame)

    warnings: list[str] = []
    if source == "raw":
        warnings.append("Using raw data because filtered/log2 data is unavailable.")
    return source, frame, warnings


def _best_distribution_source(kind: AnnotationKind) -> tuple[DataSource, pd.DataFrame, list[str]]:
    raw_frame = _get_current_frame(kind)
    annotation = get_annotation(kind)
    warnings: list[str] = []

    if annotation is not None and not annotation.log2_data.empty:
        return "log2", annotation.log2_data.copy(), warnings
    if annotation is not None and not annotation.filtered_data.empty:
        warnings.append("Log2 data unavailable; using filtered data.")
        return "filtered", annotation.filtered_data.copy(), warnings

    warnings.append("Log2/filtered data unavailable; using raw data.")
    return "raw", raw_frame, warnings


def run_imputation(payload: ImputationRunRequest) -> ImputationResultResponse:
    source_used, source_data, warnings = _best_imputation_source(payload.kind)
    sample_columns = _get_sample_columns(payload.kind, source_data)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {payload.kind} dataset.")

    diagnostics = impute_values_with_diagnostics(
        data=source_data,
        sample_columns=sample_columns,
        q=payload.qValue,
        adj_std=payload.adjustStd,
        seed=payload.seed,
        sample_wise=payload.sampleWise,
    )

    before_hist = comparative_histogram(
        diagnostics.before_without_missing,
        diagnostics.before_with_missing,
        bins=30,
    )
    overall_hist = histogram(diagnostics.overall_observed, bins=30)
    fit_curve = normal_fit_curve(diagnostics.overall_observed, points=200)
    after_hist = comparative_histogram(
        diagnostics.after_non_imputed,
        diagnostics.after_imputed,
        bins=30,
    )

    return ImputationResultResponse(
        kind=payload.kind,
        sourceUsed=source_used,
        rows=len(diagnostics.imputed_data),
        columns=len(diagnostics.imputed_data.columns),
        sampleColumns=sample_columns,
        missingBefore=diagnostics.missing_before,
        missingAfter=diagnostics.missing_after,
        mean=diagnostics.mean,
        std=diagnostics.std,
        quantile=diagnostics.quantile,
        qValue=payload.qValue,
        adjustStd=payload.adjustStd,
        seed=payload.seed,
        sampleWise=payload.sampleWise,
        beforeMissingHistogram=[
            ComparativeHistogramBin(
                start=start,
                end=end,
                leftCount=left,
                rightCount=right,
            )
            for start, end, left, right in before_hist
        ],
        overallHistogram=[
            HistogramBin(start=start, end=end, count=count) for start, end, count in overall_hist
        ],
        normalFitCurve=[CurvePoint(x=x, y=y) for x, y in fit_curve],
        afterImputationHistogram=[
            ComparativeHistogramBin(
                start=start,
                end=end,
                leftCount=left,
                rightCount=right,
            )
            for start, end, left, right in after_hist
        ],
        warnings=warnings,
        preview=_preview(diagnostics.imputed_data, rows=20),
    )


def imputed_dataframe(payload: ImputationRunRequest) -> pd.DataFrame:
    _, source_data, _ = _best_imputation_source(payload.kind)
    sample_columns = _get_sample_columns(payload.kind, source_data)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {payload.kind} dataset.")

    diagnostics = impute_values_with_diagnostics(
        data=source_data,
        sample_columns=sample_columns,
        q=payload.qValue,
        adj_std=payload.adjustStd,
        seed=payload.seed,
        sample_wise=payload.sampleWise,
    )
    return diagnostics.imputed_data


def distribution_summary(kind: AnnotationKind) -> DistributionSummaryResponse:
    source_used, data, warnings = _best_distribution_source(kind)
    sample_columns = _get_sample_columns(kind, data)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = data[sample_columns].apply(pd.to_numeric, errors="coerce")
    values = numeric.values.flatten()
    missing_count = int(np.isnan(values).sum())
    observed = values[~np.isnan(values)]

    if observed.size == 0:
        stats = ValueDistributionStats(
            count=0,
            missingCount=missing_count,
            min=None,
            max=None,
            mean=None,
            median=None,
            std=None,
        )
        qq_data = {"points": [], "fitLine": []}
    else:
        stats = ValueDistributionStats(
            count=int(observed.size),
            missingCount=missing_count,
            min=float(np.min(observed)),
            max=float(np.max(observed)),
            mean=float(np.mean(observed)),
            median=float(np.median(observed)),
            std=float(np.std(observed)),
        )
        qq_data = qqnorm_plot_data(observed, max_points=100_000)

    row_missing = numeric.isna().any(axis=1)
    rows_with_missing = int(row_missing.sum())
    rows_without_missing = int((~row_missing).sum())

    return DistributionSummaryResponse(
        kind=kind,
        sourceUsed=source_used,
        sampleColumns=sample_columns,
        stats=stats,
        rowsWithMissing=rows_with_missing,
        rowsWithoutMissing=rows_without_missing,
        qqPlot=[QQPoint(theoretical=x, sample=y) for x, y in qq_data["points"]],
        qqFitLine=[CurvePoint(x=x, y=y) for x, y in qq_data["fitLine"]],
        warnings=warnings,
    )


def verification_summary(kind: AnnotationKind) -> VerificationSummaryResponse:
    verification_frame, sample_columns = _verification_frame(kind)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = verification_frame[sample_columns].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    values = numeric.values.flatten()
    observed = values[~np.isnan(values)]

    first_digit = first_digit_distribution_data(observed)
    pattern = data_pattern_structure_data(observed)

    return VerificationSummaryResponse(
        kind=kind,
        sampleColumns=sample_columns,
        firstDigit=[
            FirstDigitPoint(digit=digit, observed=obs, benford=benford)
            for digit, obs, benford in first_digit
        ],
        duplicateFrequency=[
            DuplicateFrequencyPoint(occurrences=occ, percentage=pct) for occ, pct in pattern
        ],
        numericValueCount=int(observed.size),
    )


def run_id_translation(payload: IdTranslationRequest) -> IdTranslationResponse:
    return run_id_translation_service(payload)


def export_id_translation(payload: IdTranslationRequest) -> tuple[str, bytes, str]:
    return export_id_translation_service(payload)


def get_condition_palette_config(kind: AnnotationKind) -> ConditionPaletteResponse:
    return ConditionPaletteResponse(
        kind=kind,
        palette=get_condition_palette(kind),
    )


def update_condition_palette_config(
    kind: AnnotationKind,
    payload: ConditionPaletteUpdateRequest,
) -> ConditionPaletteResponse:
    updated = set_condition_palette(kind, payload.palette)
    return ConditionPaletteResponse(
        kind=kind,
        palette=updated,
    )

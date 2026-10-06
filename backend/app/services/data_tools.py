from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationImputationInfo, AnnotationKind
from app.schemas.data_tools import (
    ConditionPaletteResponse,
    ConditionPaletteUpdateRequest,
    ComparativeHistogramBin,
    CurvePoint,
    ResolvedSource,
    DistributionSummaryResponse,
    IdTranslationRequest,
    IdTranslationResponse,
    HistogramBin,
    ImputationResultResponse,
    ImputationRunRequest,
    QQPoint,
    ValueDistributionStats,
)
from app.services.annotation_store import get_annotation, save_annotation
from app.services.condition_palette_store import get_condition_palette
from app.services.condition_palette_store import set_condition_palette
from app.services.dataset_store import get_current_dataset
from app.services.id_translation import export_id_translation as export_id_translation_service
from app.services.id_translation import run_id_translation as run_id_translation_service
from app.services.functions import (
    QQ_MAX_POINTS,
    choose_best_source,
    comparative_histogram,
    histogram,
    impute_values_with_diagnostics,
    inverse_log2_transform_data,
    normal_fit_curve,
    qc_matrix,
    qqnorm_plot_data,
)
from app.services.runtime_cache import apply_cached_wrappers


def _preview(df: pd.DataFrame, rows: int = 20) -> list[dict[str, object]]:
    return df.head(rows).where(pd.notna(df.head(rows)), None).to_dict(orient="records")


def _get_current_frame(kind: AnnotationKind) -> pd.DataFrame:
    current = get_current_dataset(kind)
    if current is None or not hasattr(current, "frame"):
        raise ValueError(f"No {kind} dataset is currently loaded.")
    return current.frame.copy()



def log2_qc_frame(kind: AnnotationKind) -> pd.DataFrame:
    """The QC matrix: normalized, unfiltered, non-imputed log2 values.

    Every QC figure and table reads this one frame -- coverage, distribution,
    boxplot, histogram and the rest -- so the report's normalization sentence
    holds for all of them.
    """
    return qc_matrix(kind)[0]


def linear_qc_frame(kind: AnnotationKind) -> pd.DataFrame:
    """The normalized, unfiltered, non-imputed QC matrix back-transformed to linear.

    CV and abundance use the same processed values as the other QC plots.
    This does not reconstruct instrument-raw intensities after normalization.
    """
    frame, meta = qc_matrix(kind)
    columns = [column for column in meta["sample"].astype(str).tolist() if column in frame.columns]
    if not columns:
        return frame.copy()
    return inverse_log2_transform_data(frame, columns).reindex(columns=frame.columns)


def metadata_for_kind(kind: AnnotationKind, frame: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    """The annotation metadata for these sample columns, in their order.

    Samples the annotation does not know get condition "sample". Without an
    annotation every sample is its own condition. One definition, where four
    identical copies used to live.
    """
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        meta = meta[meta["sample"].isin(sample_columns)]
        if not meta.empty:
            meta = meta.drop_duplicates(subset=["sample"])
            meta = meta.set_index("sample").reindex(sample_columns).reset_index()
            meta["condition"] = meta["condition"].fillna("sample").astype(str)
            return meta

    return pd.DataFrame({"sample": sample_columns, "condition": ["sample"] * len(sample_columns)}).copy()



def _get_sample_columns(kind: AnnotationKind, frame: pd.DataFrame) -> list[str]:
    annotation = get_annotation(kind)
    if annotation is not None:
        cols = [c for c in annotation.metadata["sample"].tolist() if c in frame.columns]
        if cols:
            return cols
    return []


def skipped_sample_warnings(diagnostics) -> list[str]:
    """Samples whose missing values were left as they are, named.

    A sample with fewer than two observations, or none with any spread, has
    nothing to draw a distribution from, so its missing values survive
    imputation. The count still reports as imputed overall, so without this the
    gap is invisible. Shared with the viewer's bootstrap, which reported
    `applied=True` and said nothing about the samples it had to skip.
    """
    skipped = list(getattr(diagnostics, "skipped_samples", []) or [])
    if not skipped:
        return []
    return [
        "Missing values left unchanged: fewer than two observations or no usable "
        "spread in sample(s): " + ", ".join(skipped)
    ]


def require_imputable_kind(kind: AnnotationKind) -> None:
    if kind == "phosprot":
        raise ValueError(
            "Direct phosphoprotein imputation is disabled. Impute phosphosite data "
            "first, then aggregate phosphoproteins using the imputed phosphosite source."
        )


def _best_imputation_source(kind: AnnotationKind) -> tuple[ResolvedSource, pd.DataFrame, list[str]]:
    require_imputable_kind(kind)
    raw_frame = _get_current_frame(kind)
    annotation = get_annotation(kind)
    filtered = annotation.filtered_data if annotation is not None else None
    log2 = annotation.log2_data if annotation is not None else None
    source, frame = choose_best_source(filtered, log2, raw_frame)

    warnings: list[str] = []
    if source == "raw":
        warnings.append("Using raw data because filtered/log2 data is unavailable.")
    return source, frame, warnings


def _persist_imputation_result(
    payload: ImputationRunRequest,
    *,
    sample_columns: list[str],
    missing_before: int,
    missing_after: int,
    imputed_data: pd.DataFrame,
) -> None:
    require_imputable_kind(payload.kind)
    annotation = get_annotation(payload.kind)
    if annotation is None:
        return
    from app.app_version import APP_VERSION
    imputation_info = AnnotationImputationInfo(
        toolVersion=APP_VERSION,
        mode=payload.method,
        applied=True,
        qValue=payload.qValue,
        adjustStd=payload.adjustStd,
        downShift=payload.downShift,
        width=payload.width,
        seed=payload.seed,
        sampleWise=payload.sampleWise,
        sampleCount=len(sample_columns),
        rowCount=int(len(imputed_data)),
        missingBefore=missing_before,
        missingAfter=missing_after,
    )
    save_annotation(
        kind=annotation.kind,
        source_data=annotation.source_data,
        metadata=annotation.metadata,
        log2_data=annotation.log2_data,
        filtered_data=annotation.filtered_data,
        is_log2_transformed=annotation.is_log2_transformed,
        metadata_source=annotation.metadata_source,
        filter_config=annotation.filter_config,
        auto_detected=annotation.auto_detected,
        warnings=annotation.warnings,
        log2_auto_detected=getattr(annotation, "log2_auto_detected", False),
        imputation=imputation_info,
        imputed_data=imputed_data,
        phosprot_aggregation=getattr(annotation, "phosprot_aggregation", None),
        phosprot_lineage=getattr(annotation, "phosprot_lineage", None),
    )


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
        method=payload.method,
        down_shift=payload.downShift,
        width=payload.width,
    )

    before_hist = comparative_histogram(
        diagnostics.before_without_missing,
        diagnostics.before_with_missing,
        bins=30,
    )
    overall_hist = histogram(diagnostics.overall_observed, bins=30)
    fit_curve = normal_fit_curve(diagnostics.overall_observed, points=200, ddof=1)
    after_hist = comparative_histogram(
        diagnostics.after_non_imputed,
        diagnostics.after_imputed,
        bins=30,
    )
    _persist_imputation_result(
        payload,
        sample_columns=sample_columns,
        missing_before=diagnostics.missing_before,
        missing_after=diagnostics.missing_after,
        imputed_data=diagnostics.imputed_data,
    )

    return ImputationResultResponse(
        kind=payload.kind,
        method=payload.method,
        sourceUsed=source_used,
        rows=len(diagnostics.imputed_data),
        columns=len(diagnostics.imputed_data.columns),
        sampleColumns=sample_columns,
        missingBefore=diagnostics.missing_before,
        missingAfter=diagnostics.missing_after,
        mean=diagnostics.mean if np.isfinite(diagnostics.mean) else None,
        std=diagnostics.std if np.isfinite(diagnostics.std) else None,
        quantile=diagnostics.quantile if np.isfinite(diagnostics.quantile) else None,
        qValue=payload.qValue,
        adjustStd=payload.adjustStd,
        downShift=payload.downShift,
        width=payload.width,
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
        warnings=warnings + skipped_sample_warnings(diagnostics),
        preview=diagnostics.imputed_data.head(20).astype(object).where(
            diagnostics.imputed_data.head(20).notna(), None
        ).to_dict(orient="records"),
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
        method=payload.method,
        down_shift=payload.downShift,
        width=payload.width,
    )
    return diagnostics.imputed_data


def distribution_summary(kind: AnnotationKind) -> DistributionSummaryResponse:
    # Distribution is a QC surface: it describes the data as annotated, and it
    # offers no selector. It used to read its own resolver, which substituted
    # the filtered and then the raw matrix when log2 was missing -- so the
    # numbers beside the Q-Q plot could describe a different matrix from the
    # plot itself, which reads qc_matrix.
    data, _ = qc_matrix(kind)
    source_used: ResolvedSource = "data"
    warnings: list[str] = []
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
        finite = observed[np.isfinite(observed)]
        qq_data = qqnorm_plot_data(finite, max_points=QQ_MAX_POINTS)
        if finite.size > QQ_MAX_POINTS:
            warnings.append(
                f"The Q-Q plot shows a random sample of {QQ_MAX_POINTS:,} of the "
                f"{int(finite.size):,} observed values."
            )

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


apply_cached_wrappers(
    globals(),
    [
        "run_imputation",
        "imputed_dataframe",
        "distribution_summary",
    ],
)

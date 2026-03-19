from __future__ import annotations

import math
import re
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.schemas.completeness import CompletenessTablesResponse

FilterMode = Literal["per_group", "in_at_least_one_group"]
DataSource = Literal["filtered", "log2", "raw"]

AUTO_SAMPLE_PATTERN = re.compile(r"20\d{6}")


@dataclass
class MetadataBuildResult:
    metadata: pd.DataFrame
    auto_detected: bool


@dataclass
class ImputationDiagnostics:
    imputed_data: pd.DataFrame
    missing_before: int
    missing_after: int
    mean: float
    std: float
    quantile: float
    before_without_missing: np.ndarray
    before_with_missing: np.ndarray
    overall_observed: np.ndarray
    after_non_imputed: np.ndarray
    after_imputed: np.ndarray


# Data Pipeline
def build_metadata_from_conditions(
    data: pd.DataFrame,
    conditions: list[dict[str, object]],
) -> MetadataBuildResult:
    rows: list[dict[str, str]] = []
    used_samples: set[str] = set()

    for condition in conditions:
        name = str(condition.get("name", "")).strip()
        columns = condition.get("columns", [])
        if not name or not isinstance(columns, list):
            continue
        for col in columns:
            sample = str(col)
            if sample in used_samples or sample not in data.columns:
                continue
            rows.append({"sample": sample, "condition": name})
            used_samples.add(sample)

    if rows:
        return MetadataBuildResult(metadata=pd.DataFrame(rows), auto_detected=False)

    auto_columns = [str(col) for col in data.columns if AUTO_SAMPLE_PATTERN.search(str(col))]
    if not auto_columns:
        raise ValueError(
            "No valid condition assignments were provided and no auto-detectable sample "
            "columns were found (expected names like 20240131)."
        )
    auto_rows = [{"sample": col, "condition": "sample"} for col in auto_columns]
    return MetadataBuildResult(metadata=pd.DataFrame(auto_rows), auto_detected=True)


def log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    selected.replace(0, np.nan, inplace=True)
    log2_data = np.log2(selected)
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([log2_data, data[remaining]], axis=1)


def use_existing_log2_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([selected, data[remaining]], axis=1)


def inverse_log2_transform_data(data: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
    selected = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce")
    original = 2 ** selected
    remaining = [col for col in data.columns if col not in sample_columns]
    return pd.concat([original, data[remaining]], axis=1)


def filter_data(
    data: pd.DataFrame,
    metadata: pd.DataFrame,
    min_present: int,
    mode: FilterMode,
) -> pd.DataFrame:
    sample_columns = metadata["sample"].tolist()
    data_selected = data[sample_columns].copy()
    conditions = metadata["condition"].unique()

    mask = pd.DataFrame(False, index=data_selected.index, columns=conditions)
    for condition in conditions:
        cols = metadata.loc[metadata["condition"] == condition, "sample"].tolist()
        mask[condition] = data_selected[cols].notna().sum(axis=1) >= min_present

    rows_to_keep = mask.all(axis=1) if mode == "per_group" else mask.any(axis=1)
    return data.loc[rows_to_keep].reset_index(drop=True)


def choose_best_source(
    filtered_df: pd.DataFrame | None,
    log2_df: pd.DataFrame | None,
    raw_df: pd.DataFrame,
) -> tuple[DataSource, pd.DataFrame]:
    if filtered_df is not None and not filtered_df.empty:
        return "filtered", filtered_df.copy()
    if log2_df is not None and not log2_df.empty:
        return "log2", log2_df.copy()
    return "raw", raw_df.copy()


def impute_values_with_diagnostics(
    data: pd.DataFrame,
    sample_columns: list[str],
    q: float = 0.01,
    adj_std: float = 1.0,
    seed: int = 1337,
    sample_wise: bool = False,
) -> ImputationDiagnostics:
    np.random.seed(seed)
    numeric = data[sample_columns].copy().apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    missing_mask = numeric.isna()
    row_has_missing = missing_mask.any(axis=1)

    all_values = numeric.values.flatten()
    observed = all_values[~np.isnan(all_values)]
    if observed.size == 0:
        raise ValueError("No numeric values available for imputation.")

    before_without = numeric.loc[~row_has_missing].values.flatten()
    before_with = numeric.loc[row_has_missing].values.flatten()
    before_without = before_without[~np.isnan(before_without)]
    before_with = before_with[~np.isnan(before_with)]

    mean_val = float(np.nanmean(observed))
    std_val = float(np.nanstd(observed))
    quantile_val = float(np.nanquantile(observed, q))

    imputed_numeric = numeric.copy()
    missing_before = int(imputed_numeric.isna().sum().sum())

    if sample_wise:
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            col_observed = col_values.dropna().values
            if col_observed.size == 0:
                draws = np.random.normal(quantile_val, std_val * adj_std, missing_count)
            else:
                col_q = float(np.nanquantile(col_observed, q))
                col_sd = float(np.nanstd(col_observed))
                draw_sd = col_sd if col_sd > 0 else std_val
                draws = np.random.normal(col_q, draw_sd, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws
    else:
        draw_sd = std_val * adj_std
        for col in sample_columns:
            col_values = imputed_numeric[col]
            missing_count = int(col_values.isna().sum())
            if missing_count <= 0:
                continue
            draws = np.random.normal(quantile_val, draw_sd, missing_count)
            imputed_numeric.loc[col_values.isna(), col] = draws

    result = data.copy()
    result[sample_columns] = imputed_numeric
    missing_after = int(result[sample_columns].isna().sum().sum())

    after_imputed = imputed_numeric[missing_mask].values.flatten()
    after_non_imputed = imputed_numeric[~missing_mask].values.flatten()
    after_imputed = after_imputed[~np.isnan(after_imputed)]
    after_non_imputed = after_non_imputed[~np.isnan(after_non_imputed)]

    return ImputationDiagnostics(
        imputed_data=result,
        missing_before=missing_before,
        missing_after=missing_after,
        mean=mean_val,
        std=std_val,
        quantile=quantile_val,
        before_without_missing=before_without,
        before_with_missing=before_with,
        overall_observed=observed,
        after_non_imputed=after_non_imputed,
        after_imputed=after_imputed,
    )


def histogram(values: np.ndarray, bins: int = 30) -> list[tuple[float, float, int]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    counts, edges = np.histogram(clean, bins=bins)
    return [(float(edges[i]), float(edges[i + 1]), int(counts[i])) for i in range(len(counts))]


def comparative_histogram(
    left_values: np.ndarray,
    right_values: np.ndarray,
    bins: int = 30,
) -> list[tuple[float, float, int, int]]:
    left_clean = left_values[~np.isnan(left_values)]
    right_clean = right_values[~np.isnan(right_values)]
    combined = np.concatenate([left_clean, right_clean]) if left_clean.size or right_clean.size else np.array([])
    if combined.size == 0:
        return []
    _, edges = np.histogram(combined, bins=bins)
    left_counts, _ = np.histogram(left_clean, bins=edges)
    right_counts, _ = np.histogram(right_clean, bins=edges)
    return [
        (float(edges[i]), float(edges[i + 1]), int(left_counts[i]), int(right_counts[i]))
        for i in range(len(edges) - 1)
    ]


def normal_fit_curve(values: np.ndarray, points: int = 200) -> list[tuple[float, float]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    std_val = float(np.std(clean))
    if std_val <= 0:
        return []
    mean_val = float(np.mean(clean))
    x = np.linspace(np.min(clean), np.max(clean), points)
    y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
    return [(float(px), float(py)) for px, py in zip(x, y)]


def qqnorm_plot_data(values: np.ndarray, max_points: int = 100_000) -> dict[str, list[tuple[float, float]]]:
    clean = values[~np.isnan(values)]
    clean = clean[clean > 0]
    if clean.size == 0:
        return {"points": [], "fitLine": []}

    if clean.size > max_points:
        np.random.seed(187)
        clean = np.random.choice(clean, max_points, replace=False)

    clean = np.sort(clean)
    n = clean.size
    normal = NormalDist()

    theoretical = np.array([normal.inv_cdf((i - 0.5) / n) for i in range(1, n + 1)])
    sample = clean.astype(float)

    if n < 2:
        return {
            "points": [(float(theoretical[0]), float(sample[0]))],
            "fitLine": [],
        }

    slope, intercept = np.polyfit(theoretical, sample, 1)
    x0, x1 = float(np.min(theoretical)), float(np.max(theoretical))
    y0, y1 = float(slope * x0 + intercept), float(slope * x1 + intercept)

    return {
        "points": [(float(tx), float(sy)) for tx, sy in zip(theoretical, sample)],
        "fitLine": [(x0, y0), (x1, y1)],
    }


def first_digit_distribution_data(values: np.ndarray) -> list[tuple[int, float, float]]:
    clean = values[~np.isnan(values)]
    clean = clean[clean > 0]
    first_digits: list[int] = []
    for value in clean:
        digit = int(str(int(value))[0])
        if 1 <= digit <= 9:
            first_digits.append(digit)
    digit_freq = pd.Series(first_digits).value_counts(normalize=True).sort_index() if first_digits else pd.Series(dtype=float)
    return [
        (digit, float(digit_freq.get(digit, 0.0)), float(math.log10(1 + 1 / digit)))
        for digit in range(1, 10)
    ]


def data_pattern_structure_data(values: np.ndarray) -> list[tuple[int, float]]:
    clean = values[~np.isnan(values)]
    if clean.size == 0:
        return []
    value_freq = pd.Series(clean).value_counts()
    freq_of_freq = value_freq.value_counts().sort_index()
    total = float(freq_of_freq.sum()) if float(freq_of_freq.sum()) > 0 else 1.0
    return [(int(occ), float((count / total) * 100.0)) for occ, count in freq_of_freq.items()]


# Imputation Pipeline
def imputation_before_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    from app.services.plot_images import imputation_before_plot as _impl

    return _impl(kind, q_value, adjust_std, seed, sample_wise)


def imputation_overall_fit_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    from app.services.plot_images import imputation_overall_fit_plot as _impl

    return _impl(kind, q_value, adjust_std, seed, sample_wise)


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    from app.services.plot_images import imputation_after_plot as _impl

    return _impl(kind, q_value, adjust_std, seed, sample_wise)


# Distribution Pipeline
def distribution_qqnorm_plot(kind: AnnotationKind) -> bytes:
    from app.services.plot_images import distribution_qqnorm_plot as _impl

    return _impl(kind)


# Verification Pipeline
def verification_first_digit_plot(kind: AnnotationKind) -> bytes:
    from app.services.plot_images import verification_first_digit_plot as _impl

    return _impl(kind)


def verification_duplicate_pattern_plot(kind: AnnotationKind) -> bytes:
    from app.services.plot_images import verification_duplicate_pattern_plot as _impl

    return _impl(kind)


# Completeness Pipeline
def completeness_missing_value_plot(
    kind: AnnotationKind,
    bin_count: int = 0,
    header: bool = True,
    text: bool = True,
    text_size: int = 8,
    color: str = "#2563eb",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_plot as _impl

    return _impl(
        kind=kind,
        bin_count=bin_count,
        header=header,
        text=text,
        text_size=text_size,
        color=color,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def completeness_missing_value_heatmap(
    kind: AnnotationKind,
    include_id: bool = True,
    header: bool = True,
    width_cm: float = 10,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.completeness_tools import completeness_missing_value_heatmap as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def completeness_tables(
    kind: AnnotationKind,
    outlier_threshold: float = 50.0,
    include_id: bool = True,
) -> CompletenessTablesResponse:
    from app.services.completeness_tools import completeness_tables as _impl

    return _impl(
        kind=kind,
        outlier_threshold=outlier_threshold,
        include_id=include_id,
    )


# QC Pipeline
def qc_coverage_plot(
    kind: AnnotationKind,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_coverage_plot as _impl

    return _impl(
        kind=kind,
        include_id=include_id,
        header=header,
        legend=legend,
        summary=summary,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_intensity_histogram_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_intensity_histogram_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_boxplot_plot(
    kind: AnnotationKind,
    mode: str = "Mean",
    outliers: bool = False,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_boxplot_plot as _impl

    return _impl(
        kind=kind,
        mode=mode,
        outliers=outliers,
        include_id=include_id,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_cv_plot(
    kind: AnnotationKind,
    outliers: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    text_size: int = 9,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_cv_plot as _impl

    return _impl(
        kind=kind,
        outliers=outliers,
        header=header,
        legend=legend,
        text=text,
        text_size=text_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_pca_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    add_ellipses: bool = False,
    dot_size: int = 5,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_pca_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_pca_interactive_html(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    add_ellipses: bool = False,
    dot_size: int = 8,
    width_cm: float = 20,
    height_cm: float = 10,
) -> str:
    from app.services.plot_images import qc_pca_interactive_html as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        plot_dim=plot_dim,
        add_ellipses=add_ellipses,
        dot_size=dot_size,
        width_cm=width_cm,
        height_cm=height_cm,
    )


def qc_abundance_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from app.services.plot_images import qc_abundance_plot as _impl

    return _impl(
        kind=kind,
        header=header,
        legend=legend,
        condition=condition,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def qc_abundance_interactive_html(
    kind: AnnotationKind,
    condition: str = "All Conditions",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
) -> str:
    from app.services.plot_images import qc_abundance_interactive_html as _impl

    return _impl(
        kind=kind,
        condition=condition,
        header=header,
        legend=legend,
        width_cm=width_cm,
        height_cm=height_cm,
    )


def qc_correlation_plot(
    kind: AnnotationKind,
    method: str = "Matrix",
    include_id: bool = False,
    full_range: bool = False,
    width_cm: float = 20,
    height_cm: float = 16,
    dpi: int = 400,
) -> bytes:
    from app.services.plot_images import qc_correlation_plot as _impl

    return _impl(
        kind=kind,
        method=method,
        include_id=include_id,
        full_range=full_range,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )

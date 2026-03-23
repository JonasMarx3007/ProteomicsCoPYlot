from __future__ import annotations

import colorsys
import io
import math
import re

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.functions import (
    choose_best_source,
    impute_values_with_diagnostics,
    inverse_log2_transform_data,
    qqnorm_plot_data,
)


def _get_plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for plot rendering. Install it with: "
            "pip install matplotlib"
        ) from exc


def _get_plotly():
    try:
        import plotly.express as px
        import plotly.graph_objects as go

        return px, go
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "plotly is required for interactive plots. Install it with: "
            "pip install plotly"
        ) from exc


def _to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"format": "png", "dpi": max(72, int(dpi))}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    fig.savefig(buf, **save_kwargs)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _cm_to_inch(value_cm: float) -> float:
    return max(1.0, float(value_cm) / 2.54)


def _cm_to_px(value_cm: float) -> int:
    return max(240, int(round(float(value_cm) * (96.0 / 2.54))))


def _make_fig(plt, width_cm: float, height_cm: float):
    return plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))


def _plotly_html(fig) -> str:
    body = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "responsive": True},
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "html,body{margin:0;padding:0;background:#fff;width:100%;height:100%;}"
        "#plot-root{width:100%;height:100%;}"
        ".js-plotly-plot,.plotly-graph-div{width:100%!important;}"
        "</style>"
        "</head><body>"
        "<div id='plot-root'>"
        f"{body}"
        "</div>"
        "<script>"
        "(function(){"
        "function resizePlot(){"
        "var el=document.querySelector('.js-plotly-plot');"
        "if(el && window.Plotly){window.Plotly.Plots.resize(el);}"
        "}"
        "window.addEventListener('load', resizePlot);"
        "window.addEventListener('resize', resizePlot);"
        "setTimeout(resizePlot, 80);"
        "})();"
        "</script>"
        "</body></html>"
    )


def _imputation_source(kind: AnnotationKind):
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    filtered = annotation.filtered_data if annotation is not None else None
    log2 = annotation.log2_data if annotation is not None else None
    source_name, frame = choose_best_source(filtered, log2, raw)
    return source_name, frame


def _verification_frame(kind: AnnotationKind):
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is None:
        return raw

    sample_columns = [c for c in annotation.metadata["sample"].tolist() if c in annotation.log2_data.columns]
    if not sample_columns:
        return raw

    if annotation.is_log2_transformed:
        return inverse_log2_transform_data(annotation.log2_data, sample_columns)
    return annotation.source_data.copy()


def _distribution_frame(kind: AnnotationKind):
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.log2_data.empty:
        return annotation.log2_data.copy()
    if annotation is not None and not annotation.filtered_data.empty:
        return annotation.filtered_data.copy()
    return raw


def _coverage_frame(kind: AnnotationKind):
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.source_data.empty:
        return annotation.source_data.copy()
    return raw


def _log2_qc_frame(kind: AnnotationKind):
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.log2_data.empty:
        return annotation.log2_data.copy()
    if annotation is not None and not annotation.filtered_data.empty:
        return annotation.filtered_data.copy()
    return raw


def _metadata_for_kind(kind: AnnotationKind, frame: pd.DataFrame, sample_columns: list[str]) -> pd.DataFrame:
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


def _extract_id_or_number(sample: str) -> str:
    match = re.search(r"\d+|[A-Za-z]+", str(sample))
    return match.group(0) if match else str(sample)


def _sample_label(sample: str, condition: str, index: int, include_id: bool) -> str:
    if not include_id:
        return f"{condition}_{index + 1}"
    sid = _extract_id_or_number(sample)
    return f"{condition}_{index + 1}\n({sid})"


_BASE_CONDITION_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#aec7e8",
    "#ffbb78",
    "#98df8a",
    "#ff9896",
    "#c5b0d5",
    "#c49c94",
    "#f7b6d2",
    "#c7c7c7",
    "#dbdb8d",
    "#9edae5",
]


def _normalized_conditions(conditions: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for condition in conditions:
        normalized = str(condition).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _generated_color_hex(index: int) -> str:
    if index < len(_BASE_CONDITION_COLORS):
        return _BASE_CONDITION_COLORS[index]
    hue = (index * 0.618033988749895) % 1.0
    saturation = 0.62 if index % 2 == 0 else 0.78
    value = 0.88 if (index // 2) % 2 == 0 else 0.72
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"#{int(red * 255):02x}{int(green * 255):02x}{int(blue * 255):02x}"


def _condition_colors(_plt, conditions: list[str]) -> dict[str, str]:
    ordered = _normalized_conditions(conditions)
    return {condition: _generated_color_hex(i) for i, condition in enumerate(ordered)}


def _feature_context(frame: pd.DataFrame) -> tuple[str, str, int | None, str]:
    if "Phosphoprotein" in frame.columns:
        return "Phosphoproteins per sample", "Number of phosphoproteins", int(frame["Phosphoprotein"].shape[0]), "Phosphoprotein"
    if "ProteinNames" in frame.columns:
        return "Proteins per sample", "Number of proteins", int(frame["ProteinNames"].shape[0]), "Protein"
    if "PTM_Collapse_key" in frame.columns:
        return "Phosphosites per sample", "Number of phosphosites", int(frame["PTM_Collapse_key"].shape[0]), "Phosphosite"
    return "", "Number", None, "Feature"


def _minimum_enclosing_ellipse(points: np.ndarray, tol: float = 1e-3) -> tuple[np.ndarray, np.ndarray, float]:
    n, d = points.shape
    q = np.vstack([points.T, np.ones(n)])
    qt = q.T
    u = np.ones(n) / n
    err = tol + 1.0
    while err > tol:
        x = q @ np.diag(u) @ qt
        m = np.diag(qt @ np.linalg.inv(x) @ q)
        j = int(np.argmax(m))
        step = float((m[j] - d - 1) / ((d + 1) * (m[j] - 1)))
        new_u = (1.0 - step) * u
        new_u[j] += step
        err = float(np.linalg.norm(new_u - u))
        u = new_u
    center = points.T @ u
    a = np.linalg.inv(points.T @ np.diag(u) @ points - np.outer(center, center)) / d
    u_svd, s_svd, _ = np.linalg.svd(a)
    axes = 1.0 / np.sqrt(s_svd)
    angle = float(np.degrees(np.arctan2(u_svd[1, 0], u_svd[0, 0])))
    return center, axes, angle


def imputation_before_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    plt = _get_plt()
    _, frame = _imputation_source(kind)
    sample_columns = _get_sample_columns(kind, frame)
    diagnostics = impute_values_with_diagnostics(
        data=frame,
        sample_columns=sample_columns,
        q=q_value,
        adj_std=adjust_std,
        seed=seed,
        sample_wise=sample_wise,
    )

    fig, ax = plt.subplots()
    ax.hist(
        [diagnostics.before_without_missing, diagnostics.before_with_missing],
        bins=50,
        density=True,
        alpha=0.6,
        histtype="stepfilled",
        label=["Without Missing Values", "With Missing Values"],
    )
    ax.legend()
    ax.set_title("Overall distribution of data with and without missing values")
    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    return _to_png_bytes(fig, plt)


def imputation_overall_fit_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    plt = _get_plt()
    _, frame = _imputation_source(kind)
    sample_columns = _get_sample_columns(kind, frame)
    diagnostics = impute_values_with_diagnostics(
        data=frame,
        sample_columns=sample_columns,
        q=q_value,
        adj_std=adjust_std,
        seed=seed,
        sample_wise=sample_wise,
    )

    values = diagnostics.overall_observed
    fig, ax = plt.subplots()
    ax.hist(
        values[~np.isnan(values)],
        bins=50,
        density=True,
        alpha=0.6,
        color="blue",
        histtype="stepfilled",
    )

    std_val = diagnostics.std
    mean_val = diagnostics.mean
    if std_val > 0:
        x = np.linspace(np.nanmin(values), np.nanmax(values), 200)
        y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
        ax.plot(x, y, color="red", label="Normal fit")
        ax.legend()

    ax.set_title("Overall data distribution and norm fit")
    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    return _to_png_bytes(fig, plt)


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
) -> bytes:
    plt = _get_plt()
    _, frame = _imputation_source(kind)
    sample_columns = _get_sample_columns(kind, frame)
    diagnostics = impute_values_with_diagnostics(
        data=frame,
        sample_columns=sample_columns,
        q=q_value,
        adj_std=adjust_std,
        seed=seed,
        sample_wise=sample_wise,
    )

    fig, ax = plt.subplots()
    ax.hist(
        [diagnostics.after_non_imputed, diagnostics.after_imputed],
        bins=50,
        density=True,
        alpha=0.6,
        histtype="stepfilled",
        label=["Non-Imputed Values", "Imputed Values"],
    )
    ax.legend()
    ax.set_title("Distribution of data after imputation")
    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    return _to_png_bytes(fig, plt)


def distribution_qqnorm_plot(kind: AnnotationKind) -> bytes:
    plt = _get_plt()
    frame = _distribution_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    data_values = frame[sample_columns].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    values_vector = data_values.values.flatten()
    values_vector = values_vector[~np.isnan(values_vector)]
    values_vector = values_vector[values_vector > 0]
    if values_vector.size == 0:
        raise ValueError("No positive numeric values available for QQ norm plot.")

    qq_data = qqnorm_plot_data(values_vector, max_points=100_000)
    points = qq_data["points"]
    fit_line = qq_data["fitLine"]

    if not points:
        raise ValueError("No values available for QQ plot after preprocessing.")

    x = [pt[0] for pt in points]
    y = [pt[1] for pt in points]

    fig, ax = plt.subplots()
    ax.scatter(x, y, s=6, alpha=0.5, color="black")
    if len(fit_line) >= 2:
        fx = [fit_line[0][0], fit_line[1][0]]
        fy = [fit_line[0][1], fit_line[1][1]]
        ax.plot(fx, fy, color="red", linewidth=2)
    ax.set_title("QQ Plot")
    ax.set_xlabel("Theoretical Quantiles")
    ax.set_ylabel("Sample Quantiles")
    return _to_png_bytes(fig, plt)


def verification_first_digit_plot(kind: AnnotationKind) -> bytes:
    plt = _get_plt()
    frame = _verification_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    data_values = frame[sample_columns].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    values_vector = data_values.values.flatten()
    values_vector = values_vector[~np.isnan(values_vector)]
    values_vector = values_vector[values_vector > 0]

    first_digits = [int(str(int(v))[0]) for v in values_vector if v > 0]
    first_digits = [d for d in first_digits if d in range(1, 10)]
    digit_freq = pd.Series(first_digits).value_counts(normalize=True).sort_index() if first_digits else pd.Series(dtype=float)
    benford = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

    fig, ax = plt.subplots(figsize=(8, 5))
    x_obs = digit_freq.index.tolist() if not digit_freq.empty else list(range(1, 10))
    y_obs = digit_freq.values.tolist() if not digit_freq.empty else [0.0] * 9
    ax.bar(x_obs, y_obs, color="darkgreen", label="Observed")
    for idx, val in zip(x_obs, y_obs):
        ax.text(idx, val + 0.01, f"{val:.1%}", ha="center", va="bottom", fontsize=9)
    benford_x = list(benford.keys())
    benford_y = list(benford.values())
    ax.plot(benford_x, benford_y, color="red", linewidth=2, marker="o", label="Benford")
    ax.set_xlabel("First Digit")
    ax.set_ylabel("Relative Frequency")
    ax.set_xticks(range(1, 10))
    ax.legend()
    ax.set_title("First Digit Distribution vs Benford's Law")
    plt.tight_layout()
    return _to_png_bytes(fig, plt)


def verification_duplicate_pattern_plot(kind: AnnotationKind) -> bytes:
    plt = _get_plt()
    frame = _verification_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    data_values = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    all_values = data_values.values.flatten()
    all_values = all_values[~pd.isna(all_values)]
    if all_values.size == 0:
        raise ValueError("No numeric values available for duplicate-pattern plot.")

    value_freq = pd.Series(all_values).value_counts()
    freq_of_freq = value_freq.value_counts().sort_index()
    freq_of_freq_percent = 100 * freq_of_freq / freq_of_freq.sum()

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(freq_of_freq_percent.index.astype(str), freq_of_freq_percent.values, color="skyblue")
    for bar, val in zip(bars, freq_of_freq_percent.values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            val,
            f"{val:.3f}%",
            ha="center",
            va="bottom",
            fontsize=8,
            color="blue",
        )
    ax.set_xlabel("Duplicate Number Occurrences")
    ax.set_ylabel("Percentage (%)")
    if len(freq_of_freq_percent.values) > 0:
        ax.set_ylim(0, max(freq_of_freq_percent.values) * 1.2)
    plt.tight_layout()
    return _to_png_bytes(fig, plt)


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
    plt = _get_plt()
    frame = _coverage_frame(kind).replace(0, np.nan)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    meta["id"] = meta["sample"].astype(str).apply(_extract_id_or_number)
    meta["sample_index"] = meta.groupby("condition").cumcount() + 1
    if include_id:
        meta["label"] = meta.apply(lambda row: f"{row['condition']}_{row['sample_index']}\n({row['id']})", axis=1)
    else:
        meta["label"] = meta.apply(lambda row: f"{row['condition']}_{row['sample_index']}", axis=1)
    meta["count"] = [int(numeric[col].notna().sum()) for col in meta["sample"].tolist()]

    title, y_label, red_line_value, _ = _feature_context(frame)
    conditions = meta["condition"].astype(str).dropna().unique().tolist()
    color_map = _condition_colors(plt, conditions)

    fig, ax = _make_fig(plt, width_cm, height_cm)
    if summary:
        sample_summary = meta[["label", "condition", "count"]].rename(columns={"label": "Sample", "count": "Value"})
        condition_summary = (
            sample_summary.groupby("condition", as_index=False)
            .agg(mean_value=("Value", "mean"), sd_value=("Value", "std"))
            .fillna({"sd_value": 0.0})
        )

        positions = np.arange(len(condition_summary))
        bars = ax.bar(
            positions,
            condition_summary["mean_value"].values,
            yerr=condition_summary["sd_value"].values,
            capsize=5,
            color=[color_map[str(c)] for c in condition_summary["condition"].tolist()],
            edgecolor="black",
        )

        rng = np.random.default_rng(187)
        for i, cond in enumerate(condition_summary["condition"].tolist()):
            cond_values = sample_summary.loc[sample_summary["condition"] == cond, "Value"].to_numpy(dtype=float)
            jitter = rng.uniform(-0.2, 0.2, size=len(cond_values))
            ax.scatter(
                np.full(len(cond_values), positions[i]) + jitter,
                cond_values,
                color="black",
                alpha=0.7,
                s=20,
                zorder=3,
            )

        if text:
            for bar in bars:
                height = float(bar.get_height())
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    height * 0.02,
                    f"{int(np.ceil(height))}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    fontweight="bold",
                    rotation=90,
                    color="black",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels(condition_summary["condition"].tolist(), rotation=90, ha="center")
        ax.set_xlabel("Condition")
        ymax = float(np.max(condition_summary["mean_value"].values + condition_summary["sd_value"].values))
    else:
        positions = np.arange(len(meta))
        for cond in conditions:
            cond_idx = meta.index[meta["condition"] == cond].to_numpy()
            bars = ax.bar(
                positions[cond_idx],
                meta.loc[cond_idx, "count"].values,
                label=cond,
                color=color_map[cond],
            )
            if text:
                for bar in bars:
                    height = float(bar.get_height())
                    if height <= 0:
                        continue
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        height * 0.02,
                        f"{int(np.ceil(height))}",
                        ha="center",
                        va="bottom",
                        fontsize=text_size,
                        fontweight="bold",
                        color="black",
                        rotation=90,
                    )
        ax.set_xticks(positions)
        ax.set_xticklabels(meta["label"].tolist(), rotation=90, fontsize=6)
        ax.set_xlabel("Condition")
        ymax = float(meta["count"].max()) if not meta.empty else 0.0

    if red_line_value is not None:
        ax.axhline(y=red_line_value, color="red", linestyle="--")
        ymax = max(ymax, float(red_line_value))

    ax.set_ylabel(y_label)
    if header:
        ax.set_title(title)
    else:
        ax.set_title("")

    if legend and not summary:
        ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        plt.tight_layout()

    if ymax > 0:
        ax.set_ylim(0, ymax * 1.1)

    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def qc_intensity_histogram_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    from scipy.stats import gaussian_kde

    plt = _get_plt()
    frame = _log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    mean_intensities: list[tuple[str, np.ndarray]] = []
    for condition in meta["condition"].astype(str).dropna().unique().tolist():
        cols = meta.loc[meta["condition"] == condition, "sample"].tolist()
        condition_vals = numeric[cols].mean(axis=1, skipna=True).to_numpy(dtype=float)
        condition_vals = condition_vals[np.isfinite(condition_vals)]
        if condition_vals.size > 0:
            mean_intensities.append((condition, condition_vals))

    if not mean_intensities:
        raise ValueError("No numeric values available for histogram intensity plot.")

    all_values = np.concatenate([vals for _, vals in mean_intensities])
    xmin, xmax = float(np.min(all_values)), float(np.max(all_values))
    if math.isclose(xmin, xmax):
        xmin -= 1.0
        xmax += 1.0
    x_grid = np.linspace(xmin, xmax, 1000)
    color_map = _condition_colors(plt, [condition for condition, _ in mean_intensities])

    fig, ax = _make_fig(plt, width_cm, height_cm)
    for condition, vals in mean_intensities:
        if vals.size < 2 or np.nanstd(vals) <= 0:
            ax.hist(vals, bins=20, density=True, histtype="step", color=color_map[condition], label=condition)
            continue
        kde = gaussian_kde(vals)
        density = kde(x_grid)
        ax.plot(x_grid, density, label=condition, color=color_map[condition])

    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    if header:
        ax.set_title("Distribution of measured intensity (log2)")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        plt.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


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
    from matplotlib.patches import Patch

    plt = _get_plt()
    frame = _log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    conditions = meta["condition"].astype(str).dropna().unique().tolist()
    color_map = _condition_colors(plt, conditions)

    fig, ax = _make_fig(plt, width_cm, height_cm)
    if str(mode).lower() == "single":
        meta["id"] = meta["sample"].astype(str).apply(_extract_id_or_number)
        meta["sample_index"] = meta.groupby("condition").cumcount() + 1
        if include_id:
            meta["new_sample"] = meta.apply(
                lambda row: f"{row['condition']}_{row['sample_index']} ({row['id']})",
                axis=1,
            )
        else:
            meta["new_sample"] = meta.apply(lambda row: f"{row['condition']}_{row['sample_index']}", axis=1)

        rename_dict = dict(zip(meta["sample"], meta["new_sample"]))
        renamed = numeric.rename(columns=rename_dict)
        samples = meta["new_sample"].tolist()
        grouped_data = [renamed[s].dropna().values for s in samples]
        if not grouped_data:
            raise ValueError("No numeric values available for boxplot.")

        bp = ax.boxplot(grouped_data, patch_artist=True, showfliers=outliers)
        sample_colors = [color_map[str(c)] for c in meta["condition"].tolist()]
        for patch, color in zip(bp["boxes"], sample_colors):
            patch.set_facecolor(color)

        if text:
            medians = [np.median(g) if len(g) > 0 else np.nan for g in grouped_data]
            for i, median in enumerate(medians):
                if np.isnan(median):
                    continue
                ax.text(
                    i + 1,
                    median * 1.02,
                    f"{median:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    rotation=0,
                    color="black",
                    fontweight="bold",
                )

        ax.set_xticks(range(1, len(samples) + 1))
        ax.set_xticklabels(samples, rotation=90, ha="center")
        ax.set_ylabel("log2 Intensity")
        if header:
            ax.set_title("Measured intensity values (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor="black", label=c)
                for c in conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=(1, 0.5))
            plt.subplots_adjust(right=0.8)
    else:
        mean_intensities: list[np.ndarray] = []
        medians: list[float] = []
        valid_conditions: list[str] = []
        for condition in conditions:
            cols = meta.loc[meta["condition"] == condition, "sample"].tolist()
            condition_vals = numeric[cols].mean(axis=1, skipna=True).to_numpy(dtype=float)
            condition_vals = condition_vals[np.isfinite(condition_vals)]
            if condition_vals.size == 0:
                continue
            mean_intensities.append(condition_vals)
            medians.append(float(np.median(condition_vals)))
            valid_conditions.append(condition)

        if not mean_intensities:
            raise ValueError("No numeric values available for boxplot.")

        boxprops = dict(linewidth=1.5, color="black")
        whiskerprops = dict(linewidth=1.5, color="black")
        capprops = dict(linewidth=1.5, color="black")
        medianprops = dict(linewidth=2.5, color="firebrick")
        flierprops = dict(marker="o", markerfacecolor="red", markersize=5, linestyle="none") if outliers else dict(marker="")
        positions = np.arange(1, len(mean_intensities) + 1)

        bplot = ax.boxplot(
            mean_intensities,
            patch_artist=True,
            showfliers=outliers,
            boxprops=boxprops,
            whiskerprops=whiskerprops,
            capprops=capprops,
            medianprops=medianprops,
            flierprops=flierprops,
            positions=positions,
        )
        for patch, condition in zip(bplot["boxes"], valid_conditions):
            patch.set_facecolor(color_map[condition])

        if text:
            for pos, med in zip(positions, medians):
                ax.text(
                    pos,
                    med * 1.02,
                    f"{med:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    color="black",
                    rotation=0,
                    fontweight="bold",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels(valid_conditions)
        ax.set_xlabel("Condition")
        ax.set_ylabel("log2 Intensity")
        if header:
            ax.set_title("Measured intensity values (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor="black", label=c)
                for c in valid_conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=(1, 0.5))
            plt.tight_layout(rect=[0, 0, 0.85, 1])

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        plt.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


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
    from matplotlib.patches import Patch

    plt = _get_plt()
    frame = _verification_frame(kind).replace(0, np.nan)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    valid_conditions: list[str] = []
    cv_data: list[np.ndarray] = []
    for condition in meta["condition"].astype(str).dropna().unique().tolist():
        cols = meta.loc[meta["condition"] == condition, "sample"].tolist()
        if len(cols) < 2:
            continue
        subset = numeric[cols]
        means = subset.mean(axis=1, skipna=True)
        sds = subset.std(axis=1, skipna=True)
        cv = (sds / means) * 100.0
        cv = cv[np.isfinite(cv)].to_numpy(dtype=float)
        if cv.size == 0:
            continue
        valid_conditions.append(condition)
        cv_data.append(cv)

    if not cv_data:
        raise ValueError("No numeric values available for CV plot.")

    color_map = _condition_colors(plt, valid_conditions)
    fig, ax = _make_fig(plt, width_cm, height_cm)
    boxprops = dict(linewidth=1.5, color="black")
    whiskerprops = dict(linewidth=1.5, color="black")
    capprops = dict(linewidth=1.5, color="black")
    medianprops = dict(linewidth=2.5, color="firebrick")
    flierprops = dict(marker="o", markerfacecolor="red", markersize=5, linestyle="none") if outliers else dict(marker="")
    positions = np.arange(1, len(cv_data) + 1)

    bplot = ax.boxplot(
        cv_data,
        patch_artist=True,
        showfliers=outliers,
        boxprops=boxprops,
        whiskerprops=whiskerprops,
        capprops=capprops,
        medianprops=medianprops,
        flierprops=flierprops,
        positions=positions,
    )
    for patch, condition in zip(bplot["boxes"], valid_conditions):
        patch.set_facecolor(color_map[condition])

    if text:
        for i, vals in enumerate(cv_data, start=1):
            med = float(np.median(vals))
            ax.text(i, med, f"{med:.2f}", ha="center", va="bottom", fontsize=text_size, fontweight="bold", color="black")

    ax.set_xticks(positions)
    ax.set_xticklabels(valid_conditions)
    ax.set_xlabel("Condition")
    ax.set_ylabel("Coefficient of Variation (%)")
    if header:
        ax.set_title("Coefficient of Variation")
    else:
        ax.set_title("")

    if legend:
        legend_handles = [Patch(facecolor=color_map[c], edgecolor="black", label=c) for c in valid_conditions]
        ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=(1, 0.5))
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _pca_projection(kind: AnnotationKind, plot_dim: str = "2D") -> tuple[pd.DataFrame, np.ndarray]:
    frame = _log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if len(sample_columns) < 2:
        raise ValueError("At least two sample columns are required for PCA.")

    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    data_filtered = numeric.dropna()
    if data_filtered.empty:
        raise ValueError("No complete sample rows available for PCA.")

    transposed_expr = data_filtered.T
    transposed_expr = transposed_expr.loc[:, transposed_expr.var(axis=0) > 0]
    if transposed_expr.empty:
        raise ValueError("All features have zero variance; PCA cannot be computed.")

    n_components = 3 if str(plot_dim).upper() == "3D" else 2
    if transposed_expr.shape[0] < n_components:
        raise ValueError(f"Need at least {n_components} samples for {n_components}D PCA.")

    x = transposed_expr.values
    x = x - x.mean(axis=0, keepdims=True)
    u, s, _ = np.linalg.svd(x, full_matrices=False)
    scores = u[:, :n_components] * s[:n_components]
    explained = (s ** 2) / max(float(np.sum(s ** 2)), 1e-12) * 100.0

    pcs = [f"PC{i + 1}" for i in range(n_components)]
    pca_scores = pd.DataFrame(scores, columns=pcs)
    pca_scores["sample"] = transposed_expr.index.astype(str)
    condition_map = meta.set_index("sample")["condition"].astype(str).to_dict()
    pca_scores["condition"] = pca_scores["sample"].map(condition_map).fillna("sample")
    return pca_scores, explained


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
    from matplotlib.patches import Ellipse

    plt = _get_plt()
    pca_scores, explained = _pca_projection(kind, plot_dim=plot_dim)
    n_components = 3 if str(plot_dim).upper() == "3D" else 2

    conditions = pca_scores["condition"].astype(str).dropna().unique().tolist()
    color_map = _condition_colors(plt, conditions)

    if n_components == 3:
        fig = plt.figure(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
        ax = fig.add_subplot(111, projection="3d")
        for cond in conditions:
            subset = pca_scores[pca_scores["condition"] == cond]
            ax.scatter(
                subset["PC1"],
                subset["PC2"],
                subset["PC3"],
                label=cond,
                s=max(1, dot_size) * 10,
                alpha=0.7,
                color=color_map[cond],
            )
        ax.set_xlabel(f"PC1 - {explained[0]:.2f}%")
        ax.set_ylabel(f"PC2 - {explained[1]:.2f}%")
        ax.set_zlabel(f"PC3 - {explained[2]:.2f}%")
        if header:
            ax.set_title("3D PCA Plot")
        else:
            ax.set_title("")
        if legend:
            ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc="upper left")
    else:
        fig, ax = _make_fig(plt, width_cm, height_cm)
        for cond in conditions:
            subset = pca_scores[pca_scores["condition"] == cond]
            ax.scatter(
                subset["PC1"],
                subset["PC2"],
                label=cond,
                s=max(1, dot_size) * 10,
                alpha=0.7,
                color=color_map[cond],
            )
            if add_ellipses and len(subset) > 2:
                points = subset[["PC1", "PC2"]].to_numpy()
                center, axes, angle = _minimum_enclosing_ellipse(points)
                ellipse = Ellipse(
                    xy=center,
                    width=2 * axes[0],
                    height=2 * axes[1],
                    angle=angle,
                    facecolor=color_map[cond],
                    alpha=0.15,
                    edgecolor=color_map[cond],
                    lw=1,
                )
                ax.add_patch(ellipse)

        ax.set_xlabel(f"PC1 - {explained[0]:.2f}% variance")
        ax.set_ylabel(f"PC2 - {explained[1]:.2f}% variance")
        if header:
            ax.set_title("PCA Plot")
        else:
            ax.set_title("")
        if legend:
            ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc="upper left")

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


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
    px, go = _get_plotly()
    pca_scores, explained = _pca_projection(kind, plot_dim=plot_dim)
    plot_3d = str(plot_dim).upper() == "3D"

    height_px = _cm_to_px(height_cm)
    conditions = pca_scores["condition"].astype(str).dropna().unique().tolist()
    color_map = _condition_colors(None, conditions)

    if plot_3d:
        fig = px.scatter_3d(
            pca_scores,
            x="PC1",
            y="PC2",
            z="PC3",
            color="condition",
            color_discrete_map=color_map,
            hover_data={"sample": True, "condition": True},
            opacity=0.85,
        )
        fig.update_traces(marker=dict(size=max(2, int(dot_size))))
        fig.update_layout(
            height=height_px,
            autosize=True,
            showlegend=legend,
            title="3D PCA Plot" if header else None,
            scene=dict(
                xaxis=dict(title=f"PC1 - {explained[0]:.2f}%"),
                yaxis=dict(title=f"PC2 - {explained[1]:.2f}%"),
                zaxis=dict(title=f"PC3 - {explained[2]:.2f}%"),
            ),
        )
        return _plotly_html(fig)

    fig = px.scatter(
        pca_scores,
        x="PC1",
        y="PC2",
        color="condition",
        color_discrete_map=color_map,
        hover_data={"sample": True, "condition": True},
        opacity=0.85,
    )
    fig.update_traces(marker=dict(size=max(2, int(dot_size))))
    fig.update_layout(
        height=height_px,
        autosize=True,
        showlegend=legend,
        title="PCA Plot" if header else None,
        xaxis=dict(title=f"PC1 - {explained[0]:.2f}% variance", zeroline=False),
        yaxis=dict(title=f"PC2 - {explained[1]:.2f}% variance", zeroline=False),
    )

    if add_ellipses:
        for cond in conditions:
            subset = pca_scores[pca_scores["condition"] == cond]
            if len(subset) <= 2:
                continue
            points = subset[["PC1", "PC2"]].to_numpy()
            center, axes, angle = _minimum_enclosing_ellipse(points)
            t = np.linspace(0, 2 * np.pi, 200)
            ellipse = np.array([axes[0] * np.cos(t), axes[1] * np.sin(t)])
            rotation = np.array(
                [
                    [np.cos(np.radians(angle)), -np.sin(np.radians(angle))],
                    [np.sin(np.radians(angle)), np.cos(np.radians(angle))],
                ]
            )
            ellipse_rot = rotation @ ellipse
            ellipse_x = ellipse_rot[0] + center[0]
            ellipse_y = ellipse_rot[1] + center[1]
            fig.add_trace(
                go.Scatter(
                    x=ellipse_x,
                    y=ellipse_y,
                    mode="lines",
                    fill="toself",
                    line=dict(width=1, color=color_map.get(cond, "#6b7280")),
                    fillcolor=color_map.get(cond, "#6b7280"),
                    showlegend=False,
                    hoverinfo="skip",
                    opacity=0.18,
                )
            )

    return _plotly_html(fig)


def _abundance_rank_frame(kind: AnnotationKind) -> tuple[pd.DataFrame, list[str], str]:
    frame = _verification_frame(kind).replace(0, np.nan)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError("No sample columns available for abundance plot.")

    _, _, _, workflow = _feature_context(frame)
    if workflow == "Feature":
        workflow = "Protein" if kind == "protein" else "Phosphosite"
    key_col = "ProteinNames" if workflow == "Protein" else "PTM_Collapse_key"
    if key_col not in frame.columns:
        key_col = frame.columns[0]

    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    unique_conditions = meta["condition"].astype(str).dropna().unique().tolist()
    if not unique_conditions:
        raise ValueError("No conditions available for abundance plot.")

    data_filtered = frame[[key_col] + sample_columns].copy()
    mean_intensities = pd.DataFrame({key_col: data_filtered[key_col]})
    for cond in unique_conditions:
        cols = meta.loc[meta["condition"] == cond, "sample"].tolist()
        means = data_filtered[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
        mean_intensities[cond] = np.log10(means + 1)

    if len(unique_conditions) > 1:
        keep_mask = mean_intensities[unique_conditions].isna().sum(axis=1) < (len(unique_conditions) - 1)
        mean_intensities = mean_intensities.loc[keep_mask]
    else:
        mean_intensities = mean_intensities.dropna(subset=[unique_conditions[0]])

    long_intensities = mean_intensities.melt(
        id_vars=[key_col], var_name="Condition", value_name="log10Intensity"
    )
    long_intensities = long_intensities.dropna(subset=["log10Intensity"])
    long_intensities["Rank"] = (
        long_intensities.groupby("Condition")["log10Intensity"]
        .rank(ascending=False, method="first")
    )
    long_intensities["Feature"] = long_intensities[key_col].astype(str)
    return long_intensities, unique_conditions, workflow


def qc_abundance_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    plt = _get_plt()
    frame = _verification_frame(kind).replace(0, np.nan)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError("No sample columns available for abundance plot.")

    _, _, _, workflow = _feature_context(frame)
    if workflow == "Feature":
        workflow = "Protein" if kind == "protein" else "Phosphosite"
    key_col = "ProteinNames" if workflow == "Protein" else "PTM_Collapse_key"
    if key_col not in frame.columns:
        key_col = frame.columns[0]

    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    unique_conditions = meta["condition"].astype(str).dropna().unique().tolist()
    if not unique_conditions:
        raise ValueError("No conditions available for abundance plot.")

    data_filtered = frame[[key_col] + sample_columns].copy()
    mean_intensities = pd.DataFrame({key_col: data_filtered[key_col]})
    for cond in unique_conditions:
        cols = meta.loc[meta["condition"] == cond, "sample"].tolist()
        means = data_filtered[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
        mean_intensities[cond] = np.log10(means + 1)

    if len(unique_conditions) > 1:
        keep_mask = mean_intensities[unique_conditions].isna().sum(axis=1) < (len(unique_conditions) - 1)
        mean_intensities = mean_intensities.loc[keep_mask]
    else:
        mean_intensities = mean_intensities.dropna(subset=[unique_conditions[0]])

    color_map = _condition_colors(plt, unique_conditions)
    fig, ax = _make_fig(plt, width_cm, height_cm)
    if condition == "All Conditions":
        long_intensities = mean_intensities.melt(
            id_vars=[key_col], var_name="Condition", value_name="log10Intensity"
        )
        long_intensities = long_intensities.dropna(subset=["log10Intensity"])
        long_intensities["Rank"] = (
            long_intensities.groupby("Condition")["log10Intensity"]
            .rank(ascending=False, method="first")
        )
        for cond in unique_conditions:
            subset = long_intensities[long_intensities["Condition"] == cond]
            ax.scatter(subset["Rank"], subset["log10Intensity"], label=cond, color=color_map[cond], s=5)
    else:
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        values = mean_intensities[condition].dropna().sort_values(ascending=False).reset_index(drop=True)
        ranks = np.arange(1, len(values) + 1)
        ax.scatter(ranks, values.values, label=condition, color=color_map[condition], s=7)

    ax.set_xlabel(f"{workflow} Rank")
    ax.set_ylabel(f"log10 {workflow} Intensity")
    if header:
        ax.set_title(f"Abundance plot - {workflow}")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=(1.05, 1), loc="upper left")
        fig.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        fig.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


def qc_abundance_interactive_html(
    kind: AnnotationKind,
    condition: str = "All Conditions",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
) -> str:
    px, _ = _get_plotly()
    long_intensities, unique_conditions, workflow = _abundance_rank_frame(kind)
    height_px = _cm_to_px(height_cm)

    if condition != "All Conditions":
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        long_intensities = long_intensities[long_intensities["Condition"] == condition]
    visible_conditions = long_intensities["Condition"].astype(str).dropna().unique().tolist()
    color_map = _condition_colors(None, visible_conditions)

    fig = px.scatter(
        long_intensities,
        x="Rank",
        y="log10Intensity",
        color="Condition",
        color_discrete_map=color_map,
        hover_data={"Feature": True, "Condition": True, "Rank": True, "log10Intensity": ":.4f"},
        opacity=0.85,
    )
    fig.update_traces(marker=dict(size=6))
    fig.update_layout(
        height=height_px,
        autosize=True,
        showlegend=legend,
        title=f"Abundance plot - {workflow}" if header else None,
        xaxis_title=f"{workflow} Rank",
        yaxis_title=f"log10 {workflow} Intensity",
    )
    return _plotly_html(fig)


def qc_correlation_plot(
    kind: AnnotationKind,
    method: str = "Matrix",
    include_id: bool = False,
    full_range: bool = False,
    width_cm: float = 20,
    height_cm: float = 16,
    dpi: int = 400,
) -> bytes:
    from matplotlib.patches import Ellipse

    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
        from scipy.spatial.distance import squareform

        has_scipy = True
    except ModuleNotFoundError:
        has_scipy = False

    plt = _get_plt()
    frame = _verification_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if len(sample_columns) < 2:
        fallback_cols = (
            frame.apply(pd.to_numeric, errors="coerce")
            .dropna(axis=1, how="all")
            .columns.astype(str)
            .tolist()
        )
        sample_columns = [col for col in fallback_cols if col in frame.columns]
    if len(sample_columns) < 2:
        raise ValueError("At least two sample columns are required for correlation plot.")

    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    meta["sample"] = meta["sample"].astype(str)
    meta["id"] = meta["sample"].astype(str).apply(_extract_id_or_number)
    meta["new_sample"] = meta.groupby("condition").cumcount() + 1
    if include_id:
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']} ({row['id']})",
            axis=1,
        )
    else:
        meta["new_sample"] = meta.apply(
            lambda row: f"{row['condition']}_{row['new_sample']}",
            axis=1,
        )

    rename_map = dict(zip(meta["sample"], meta["new_sample"]))
    annotated_columns = meta["new_sample"].tolist()
    data_filtered = (
        frame[sample_columns]
        .rename(columns=rename_map)
        .reindex(columns=annotated_columns)
        .apply(pd.to_numeric, errors="coerce")
    )
    data_filtered = data_filtered.dropna(axis=1, how="all")
    if data_filtered.shape[1] < 2:
        raise ValueError("At least two non-empty sample columns are required for correlation plot.")

    correlation_matrix = data_filtered.corr(method="pearson")
    if correlation_matrix.shape[0] < 2:
        raise ValueError("Correlation matrix could not be computed from selected sample columns.")

    ordered_corr = correlation_matrix
    if has_scipy and len(correlation_matrix) > 1:
        distance_matrix = 1 - correlation_matrix
        distance_matrix = distance_matrix.fillna(1.0).clip(lower=0.0, upper=2.0)
        distance_matrix = (distance_matrix + distance_matrix.T) / 2.0
        distance_np = distance_matrix.to_numpy(copy=True)
        np.fill_diagonal(distance_np, 0.0)
        try:
            linkage_matrix = linkage(
                squareform(distance_np, checks=False),
                method="complete",
            )
            ordered_idx = leaves_list(linkage_matrix)
            ordered_corr = correlation_matrix.iloc[ordered_idx, ordered_idx]
        except Exception:
            ordered_corr = correlation_matrix

    ordered_corr = ordered_corr.fillna(0.0)

    if full_range:
        vmin, vmax = -1.0, 1.0
    else:
        vmin = float(np.nanmin(ordered_corr.values))
        vmax = float(np.nanmax(ordered_corr.values))
        if math.isclose(vmin, vmax):
            vmin, vmax = -1.0, 1.0

    fig, ax = _make_fig(plt, width_cm, height_cm)
    method_normalized = str(method).strip().lower()
    if method_normalized == "matrix":
        cax = ax.matshow(ordered_corr, cmap="coolwarm", vmin=vmin, vmax=vmax)
        ax.set_xticks(range(len(ordered_corr.columns)))
        ax.set_yticks(range(len(ordered_corr.index)))
        ax.set_xticklabels(ordered_corr.columns.tolist(), rotation=90, ha="center", va="bottom", fontsize=7)
        ax.set_yticklabels(ordered_corr.index.tolist(), fontsize=7)
        fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
    elif method_normalized == "ellipse":
        n = len(ordered_corr)
        ax.set_xlim(0, n)
        ax.set_ylim(0, n)
        ax.set_xticks(np.arange(n) + 0.5)
        ax.set_yticks(np.arange(n) + 0.5)
        ax.set_xticklabels(ordered_corr.columns.tolist(), rotation=90, ha="center", va="top", fontsize=7)
        ax.set_yticklabels(ordered_corr.index.tolist(), fontsize=7)
        ax.invert_yaxis()

        for i in range(n):
            for j in range(n):
                r = float(ordered_corr.iloc[i, j])
                ellipse = Ellipse(
                    (j + 0.5, i + 0.5),
                    width=0.9,
                    height=0.9 * (1 - abs(r)),
                    angle=45 if r > 0 else -45,
                    facecolor="red" if r > 0 else "blue",
                    alpha=0.6,
                )
                ax.add_patch(ellipse)

        sm = plt.cm.ScalarMappable(cmap="coolwarm", norm=plt.Normalize(vmin=-1, vmax=1))
        fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
    else:
        raise ValueError("method must be 'Matrix' or 'Ellipse'")

    ax.set_xlabel("Samples")
    ax.set_ylabel("Samples")
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)

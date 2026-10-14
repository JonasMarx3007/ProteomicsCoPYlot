from __future__ import annotations


from app.services.peptide_quantity import resolve_peptide_quantity_column
from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
    # One pixel size for interactive figures. This module floored at 240 px and
    # plot_export at 320, so the same 6 cm plot came out narrower here than on
    # the comparison and peptide pages, which already import this one.
    cm_to_px as _cm_to_px,
)

import math
import re
from typing import Any

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.data_tools import _get_sample_columns, metadata_for_kind as _metadata_for_kind, linear_qc_frame, log2_qc_frame
from app.services.functions import (
    intensity_unit_label,
    resolve_feature_scaling,
    abundance_axis_label,
    condition_cvs,
    extract_sample_id as _extract_id_or_number,
    impute_values_with_diagnostics,
    QQ_MAX_POINTS,
    qqnorm_plot_data,
    raw_zero_to_nan,
)
from app.services.analysis_matrix import phosprot_values_are_centred, select_matrix
from app.services.runtime_cache import apply_cached_wrappers
from app.services.plotting_common import get_plt as _get_plt, get_plotly as _get_plotly, plotly_html as _plotly_html
from app.services.plot_styling import (
    advanced_anchor,
    advanced_condition_colors,
    advanced_element_text,
    advanced_label,
    advanced_number,
    advanced_plotly_layout,
    advanced_text,
    apply_advanced_axes,
    pca_default_size,
    rename_composite_sample_label,
    advanced_color_map,
    advanced_label_size,
    apply_plotly_group_markers,
    marker_style,
    resolve_reference_line,
)

def _make_fig(plt, width_cm: float, height_cm: float):
    return plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))


def _imputation_source(kind: AnnotationKind):
    """The matrix imputation runs on: the one resolver in `data_tools`, so previews match runs."""
    from app.services.data_tools import _best_imputation_source

    source_name, frame, _ = _best_imputation_source(kind)
    return source_name, frame


def peptide_file_column(frame: pd.DataFrame) -> str:
    if "File.Name" in frame.columns:
        return "File.Name"
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "file" in normalized and "name" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a file-name column.")


def peptide_sequence_column(frame: pd.DataFrame) -> str:
    if "Stripped.Sequence" in frame.columns:
        return "Stripped.Sequence"
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "stripped" in normalized and "sequence" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a stripped-sequence column.")


def peptide_precursor_column(frame: pd.DataFrame) -> str:
    if "Precursor.Id" in frame.columns:
        return "Precursor.Id"
    for column in frame.columns:
        normalized = re.sub(r"[^a-z0-9]+", "", str(column).strip().lower())
        if "precursor" in normalized and "id" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a precursor-id column.")


def _peptide_coverage_metadata(frame: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    # Reuse the exact metadata preparation used by peptide modification/missed-cleavage
    # so peptide coverage follows the same shared proteome metadata behavior.
    from app.services.peptide_tools import _prepare_metadata as _prepare_peptide_metadata

    meta = _prepare_peptide_metadata(frame, include_id=include_id).copy()
    return meta.rename(columns={"new_sample": "label"})


def _grouped_meta_order(meta: pd.DataFrame) -> pd.DataFrame:
    if meta.empty:
        return meta.copy()

    ordered = meta.copy()
    ordered["condition"] = ordered["condition"].astype(str)
    condition_order = ordered["condition"].dropna().drop_duplicates().tolist()
    if not condition_order:
        return ordered.reset_index(drop=True)

    ordered["__condition_order"] = pd.Categorical(
        ordered["condition"],
        categories=condition_order,
        ordered=True,
    )
    ordered = ordered.sort_values("__condition_order", kind="stable")
    return ordered.drop(columns="__condition_order").reset_index(drop=True)


def _sample_label(sample: str, condition: str, index: int, include_id: bool) -> str:
    if not include_id:
        return f"{condition}_{index + 1}"
    sid = _extract_id_or_number(sample)
    return f"{condition}_{index + 1}\n({sid})"



def fitted_group_ellipse(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Fit an enclosing ellipse only when the group reliably spans the plane.

    The points are copied into one row-major array first. The same values held
    column-major -- as a pandas selection can hand them over -- take another
    path through the linear algebra and can land on an ellipse that differs in
    the last bit, so the app and its exported notebook would draw different
    outlines from identical scores.
    """
    array = np.ascontiguousarray(points, dtype=float)
    if array.ndim != 2 or array.shape[0] < 3 or array.shape[1] != 2 or not np.isfinite(array).all():
        return None
    try:
        origin = array.mean(axis=0)
        centered = array - origin
        scale = np.max(np.abs(centered))
        if not np.isfinite(scale) or scale == 0:
            return None
        normalized = centered / scale
        singular = np.linalg.svd(normalized, compute_uv=False)
        # The solver inverts a scatter matrix, squaring the coordinate condition number.
        if singular[-1] <= singular[0] * np.sqrt(np.finfo(float).eps):
            return None
        center, axes, angle = _minimum_enclosing_ellipse(normalized)
        center, axes = origin + center * scale, axes * scale
    except (np.linalg.LinAlgError, ValueError, ZeroDivisionError, FloatingPointError):
        return None
    if not (np.isfinite(center).all() and np.isfinite(axes).all() and np.isfinite(angle)):
        return None
    if float(np.min(axes)) <= 0:
        return None
    return center, axes, angle


def _feature_context(
    frame: pd.DataFrame, sample_columns: list[str] | None = None
) -> tuple[str, str, int | None, str]:
    """Title, axis label, reference line and workflow name for a coverage plot.

    The reference line is the number of features quantified in **at least one**
    sample, which is what the bars below it add up to. It used to be the row
    count of the matrix, and those differ: a feature can be identified -- real
    sequence, localization, protein -- without a quantity surviving in any run.
    The HEK293 phosphosite file holds 21 such rows, so the line sat 21 above the
    union of the bars it was drawn over.
    """
    quantified = _quantified_feature_count(frame, sample_columns)
    if "Phosphoprotein" in frame.columns:
        return "Phosphoproteins per sample", "Number of phosphoproteins", quantified, "Phosphoprotein"
    if "ProteinNames" in frame.columns:
        return "Proteins per sample", "Number of proteins", quantified, "Protein"
    if "PTM_Collapse_key" in frame.columns:
        return "Phosphosites per sample", "Number of phosphosites", quantified, "Phosphosite"
    return "", "Number", None, "Feature"


def _quantified_feature_count(
    frame: pd.DataFrame, sample_columns: list[str] | None
) -> int | None:
    """Features with a value in at least one annotated sample."""
    columns = [column for column in (sample_columns or []) if column in frame.columns]
    if not columns:
        return None
    observed = frame[columns].apply(pd.to_numeric, errors="coerce").notna()
    return int(observed.any(axis=1).sum())


def _minimum_enclosing_ellipse(points: np.ndarray, tol: float = 1e-3) -> tuple[np.ndarray, np.ndarray, float]:
    n, d = points.shape
    q = np.vstack([points.T, np.ones(n)])
    qt = q.T
    u = np.ones(n) / n
    err = tol + 1.0
    for _ in range(10000):
        x = q @ np.diag(u) @ qt
        m = np.diag(qt @ np.linalg.inv(x) @ q)
        j = int(np.argmax(m))
        step = float((m[j] - d - 1) / ((d + 1) * (m[j] - 1)))
        new_u = (1.0 - step) * u
        new_u[j] += step
        err = float(np.linalg.norm(new_u - u))
        u = new_u
        if err <= tol:
            break
    else:
        raise ValueError("Enclosing ellipse did not converge.")
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
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict[str, Any] | None = None,
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
        method=method,
        down_shift=down_shift,
        width=width,
    )

    fig, ax = _make_fig(plt, 20, 10)  # the common 20 x 10 cm canvas (2026-10-09)
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
    ax.set_xlabel(intensity_unit_label(phosprot_values_are_centred(kind)))
    ax.set_ylabel("Density")
    apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt, dpi=300)


def _imputation_histogram_bin_edges(
    observed: np.ndarray,
    imputed: np.ndarray,
) -> np.ndarray:
    combined = np.concatenate([observed, imputed])
    if combined.size <= 0:
        raise ValueError("No values are available for the imputation histogram.")
    return np.histogram_bin_edges(combined, bins=50)


def imputation_overall_fit_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    show_imputation_draw: bool = True,
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict[str, Any] | None = None,
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
        method=method,
        down_shift=down_shift,
        width=width,
    )

    values = diagnostics.overall_observed
    if values.size == 0:
        raise ValueError("No observed values available to plot an imputation distribution.")
    histogram_bin_edges = _imputation_histogram_bin_edges(values, diagnostics.after_imputed)
    draw_components = diagnostics.draw_components if show_imputation_draw else []

    positive_draw_components = [component for component in draw_components if component[1] > 0]
    x_min = float(np.nanmin(values))
    x_max = float(np.nanmax(values))
    if diagnostics.std > 0:
        x_min = min(x_min, diagnostics.mean - 4 * diagnostics.std)
        x_max = max(x_max, diagnostics.mean + 4 * diagnostics.std)
    if positive_draw_components:
        x_min = min(x_min, min(center - 4 * std for center, std, _ in positive_draw_components))
        x_max = max(x_max, max(center + 4 * std for center, std, _ in positive_draw_components))
    if x_max <= x_min:
        x_min -= 1
        x_max += 1

    fig, ax = _make_fig(plt, 20, 10)  # the common 20 x 10 cm canvas (2026-10-09)
    ax.hist(
        values[~np.isnan(values)],
        bins=histogram_bin_edges,
        density=True,
        alpha=0.6,
        color="blue",
        histtype="stepfilled",
    )

    std_val = diagnostics.std
    mean_val = diagnostics.mean
    x = np.linspace(x_min, x_max, 400)
    # Both curves drawn over this histogram are guides rather than data, so they
    # answer to the reference-line settings like every other guide in the tool.
    fit_line_style = resolve_reference_line(advanced, color="red", style="solid", width=1.5)
    draw_line_style = resolve_reference_line(advanced, color="cyan", style="solid", width=2.5)
    if std_val > 0 and fit_line_style.visible:
        y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
        ax.plot(x, y, label="Normal fit", **fit_line_style.matplotlib())

    if positive_draw_components:
        total_weight = float(sum(weight for _, _, weight in positive_draw_components))
        draw_density = np.zeros_like(x)
        for center, draw_std, weight in positive_draw_components:
            component_density = (
                1 / (draw_std * np.sqrt(2 * np.pi))
            ) * np.exp(-0.5 * ((x - center) / draw_std) ** 2)
            draw_density += (weight / total_weight) * component_density
        if draw_line_style.visible:
            ax.plot(x, draw_density, label="Draw area", **draw_line_style.matplotlib())
    elif draw_components and draw_line_style.visible:
        ax.axvline(draw_components[0][0], label="Draw area", **draw_line_style.matplotlib())

    ax.legend()

    method_label = "Numerical" if str(method).strip().lower() == "numerical" else "Quantile"
    ax.set_title(f"Overall data distribution and norm fit ({method_label})")
    ax.set_xlabel(intensity_unit_label(phosprot_values_are_centred(kind)))
    ax.set_ylabel("Density")
    apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt, dpi=300)


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    normalization: str = "separate",
    method="quantile",
    down_shift=1.8,
    width=0.3,
    advanced: dict[str, Any] | None = None,
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
        method=method,
        down_shift=down_shift,
        width=width,
    )

    non_imputed = diagnostics.after_non_imputed
    imputed = diagnostics.after_imputed
    bin_edges, weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        normalization,
    )

    fig, ax = _make_fig(plt, 20, 10)  # the common 20 x 10 cm canvas (2026-10-09)
    ax.hist(
        [non_imputed, imputed],
        bins=bin_edges,
        weights=weights,
        alpha=0.6,
        histtype="stepfilled",
        label=["Non-Imputed Values", "Imputed Values"],
    )
    ax.legend()
    method_label = "Numerical" if str(method).strip().lower() == "numerical" else "Quantile"
    ax.set_title(f"Distribution of data after {method_label.lower()} imputation")
    ax.set_xlabel(intensity_unit_label(phosprot_values_are_centred(kind)))
    ax.set_ylabel("Density")
    apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt, dpi=300)


def _imputation_density_histogram_spec(
    non_imputed: np.ndarray,
    imputed: np.ndarray,
    normalization: str,
) -> tuple[np.ndarray, list[np.ndarray]]:
    normalization_mode = str(normalization or "separate").strip().lower()
    if normalization_mode not in {"together", "separate"}:
        raise ValueError("After-imputation normalization must be 'together' or 'separate'.")

    combined = np.concatenate([non_imputed, imputed])
    if combined.size <= 0:
        raise ValueError("No values are available after imputation.")

    bin_edges = _imputation_histogram_bin_edges(non_imputed, imputed)
    bin_width = float(bin_edges[1] - bin_edges[0])
    if bin_width <= 0:
        raise ValueError("A positive histogram bin width is required.")

    if normalization_mode == "separate":
        weights = [
            (
                np.full(non_imputed.size, 1.0 / (non_imputed.size * bin_width))
                if non_imputed.size
                else np.array([], dtype=float)
            ),
            (
                np.full(imputed.size, 1.0 / (imputed.size * bin_width))
                if imputed.size
                else np.array([], dtype=float)
            ),
        ]
    else:
        combined_density_weight = 1.0 / (combined.size * bin_width)
        weights = [
            np.full(non_imputed.size, combined_density_weight),
            np.full(imputed.size, combined_density_weight),
        ]

    return bin_edges, weights


def distribution_qqnorm_plot(
    kind: AnnotationKind,
    random_seed: int = 187,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    plt = _get_plt()
    frame = log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    data_values = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    values_vector = data_values.values.flatten()
    values_vector = values_vector[np.isfinite(values_vector)]
    if values_vector.size == 0:
        raise ValueError("No numeric values available for QQ norm plot.")

    qq_data = qqnorm_plot_data(values_vector, max_points=QQ_MAX_POINTS, seed=random_seed)
    points = qq_data["points"]
    fit_line = qq_data["fitLine"]

    if not points:
        raise ValueError("No values available for QQ plot after preprocessing.")

    x = [pt[0] for pt in points]
    y = [pt[1] for pt in points]

    fig, ax = _make_fig(plt, 20, 10)  # the common 20 x 10 cm canvas (2026-10-09)
    ax.scatter(x, y, **marker_style(advanced, size=2.5, alpha=0.5, color_default="black"))
    line = resolve_reference_line(advanced, color="red", style="solid", width=2.0)
    if len(fit_line) >= 2 and line.visible:
        fx = [fit_line[0][0], fit_line[1][0]]
        fy = [fit_line[0][1], fit_line[1][1]]
        ax.plot(fx, fy, **line.matplotlib())
    ax.set_title("QQ Plot")
    ax.set_xlabel("Theoretical Quantiles")
    ax.set_ylabel("Sample Quantiles")
    apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt, dpi=300)


def qc_coverage_plot(
    kind: AnnotationKind,
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    text_size: int = 9,
    random_seed: int = 187,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
    reference_line: bool = True,
) -> bytes:
    """Features per sample, with the quantified-in-any-sample total as a line.

    ``reference_line`` is the plot's own switch for that line. Off, the line is
    not drawn and the y axis is fitted to the bars alone, so they use the full
    height instead of leaving room for a line that is not there.
    """
    plt = _get_plt()
    frame = log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    meta = _grouped_meta_order(_metadata_for_kind(kind, frame, sample_columns).copy())
    meta["id"] = meta["sample"].astype(str).apply(_extract_id_or_number)
    meta["sample_index"] = meta.groupby("condition").cumcount() + 1
    if include_id:
        meta["label"] = meta.apply(lambda row: f"{row['condition']}_{row['sample_index']}\n({row['id']})", axis=1)
    else:
        meta["label"] = meta.apply(lambda row: f"{row['condition']}_{row['sample_index']}", axis=1)
    meta["count"] = [int(numeric[col].notna().sum()) for col in meta["sample"].tolist()]

    title, y_label, red_line_value, _ = _feature_context(frame, sample_columns)

    if summary:

        # The bars are condition means, not samples.

        title = title.replace("per sample", "per condition")
    conditions = meta["condition"].astype(str).dropna().unique().tolist()
    color_map = advanced_condition_colors(kind, plt, conditions, advanced)

    fig, ax = _make_fig(plt, width_cm, height_cm)
    if summary:
        sample_summary = meta[["label", "condition", "count"]].rename(columns={"label": "Sample", "count": "Value"})
        condition_summary = (
            sample_summary.groupby("condition", as_index=False, sort=False)
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

        rng = np.random.default_rng(random_seed)
        for i, cond in enumerate(condition_summary["condition"].tolist()):
            cond_values = sample_summary.loc[sample_summary["condition"] == cond, "Value"].to_numpy(dtype=float)
            jitter = rng.uniform(-0.2, 0.2, size=len(cond_values))
            ax.scatter(
                np.full(len(cond_values), positions[i]) + jitter,
                cond_values,
                zorder=3,
                **marker_style(advanced, size=4.5, alpha=0.7, color_default="black"),
            )

        if text:
            # Above the error bar rather than inside the bar, where the label
            # sat on the coloured face and the jittered dots.
            for bar, sd in zip(bars, condition_summary["sd_value"].values):
                height = float(bar.get_height())
                x_pos, y_pos = bar.get_x() + bar.get_width() / 2, height + float(sd)
                ax.text(
                    x_pos,
                    y_pos,
                    f" {int(np.ceil(height))}",
                    ha="center",
                    va="bottom",
                    fontsize=advanced_label_size(advanced, text_size),
                    fontweight="bold",
                    rotation=90,
                    color="black",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels(
            [advanced_label(condition, advanced, "conditionLabels") for condition in condition_summary["condition"].tolist()],
            rotation=90,
            ha="center",
        )
        ax.set_xlabel("Condition")
        ymax = float(np.max(condition_summary["mean_value"].values + condition_summary["sd_value"].values))
    else:
        positions = np.arange(len(meta))
        for cond in conditions:
            cond_idx = meta.index[meta["condition"] == cond].to_numpy()
            bars = ax.bar(
                positions[cond_idx],
                meta.loc[cond_idx, "count"].values,
                label=advanced_label(cond, advanced, "conditionLabels"),
                color=color_map[cond],
            )
            if text:
                for bar in bars:
                    height = float(bar.get_height())
                    if height <= 0:
                        continue
                    # Above the bar, not on its face.
                    x_pos, y_pos = bar.get_x() + bar.get_width() / 2, height
                    ax.text(
                        x_pos,
                        y_pos,
                        f" {int(np.ceil(height))}",
                        ha="center",
                        va="bottom",
                        fontsize=advanced_label_size(advanced, text_size),
                        fontweight="bold",
                        color="black",
                        rotation=90,
                    )
        ax.set_xticks(positions)
        ax.set_xticklabels(
            [
                rename_composite_sample_label(label, sample, condition, advanced)
                for label, sample, condition in zip(
                    meta["label"].tolist(),
                    meta["sample"].astype(str).tolist(),
                    meta["condition"].astype(str).tolist(),
                )
            ],
            rotation=90,
            fontsize=6,
        )
        ax.set_xlabel("Sample")
        ymax = float(meta["count"].max()) if not meta.empty else 0.0

    if red_line_value is not None and reference_line:
        line = resolve_reference_line(advanced, color="red")
        if line.visible:
            # The line says what it is in the legend (the panel can drop the
            # entry and keep the line); the bars below it add up to this total.
            label = "Total" if line.legend_entry else None
            ax.axhline(y=red_line_value, label=label, **line.matplotlib())
            ymax = max(ymax, float(red_line_value))

    ax.set_ylabel(y_label)
    if header:
        ax.set_title(title)
    else:
        ax.set_title("")

    # Summary mode has no condition entries (the x axis names them), so its
    # legend holds only the total line -- when there is one to name.
    handles, labels = ax.get_legend_handles_labels()
    # The total line first (2026-10-14; matplotlib lists lines before bars anyway, but the
    # order is made explicit), then the conditions in panel order.
    order = sorted(range(len(labels)), key=lambda i: labels[i] != "Total")
    if legend and handles and (not summary or any(labels)):
        ax.legend([handles[i] for i in order], [labels[i] for i in order],
                  title="Condition" if not summary else None,
                  bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        apply_advanced_axes(ax, advanced)
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        apply_advanced_axes(ax, advanced)
        plt.tight_layout()

    # 10 % headroom above whatever is tallest: the total line when it is drawn,
    # otherwise the tallest bar. With the line off the axis is measured from
    # the bars, not from a line that is not there. Count labels now stand on
    # top of the bars, so they need room of their own.
    headroom = 1.1 if not text else 1.25
    if ymax > 0:
        ax.set_ylim(0, ymax * headroom)

    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def qc_intensity_histogram_plot(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from scipy.stats import gaussian_kde

    plt = _get_plt()
    frame = log2_qc_frame(kind)
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
    color_map = advanced_condition_colors(kind, plt, [condition for condition, _ in mean_intensities], advanced)

    fig, ax = _make_fig(plt, width_cm, height_cm)
    for condition, vals in mean_intensities:
        label = advanced_label(condition, advanced, "conditionLabels")
        if vals.size < 2 or np.nanstd(vals) <= 0:
            ax.hist(vals, bins=20, density=True, histtype="step", color=color_map[condition], label=label)
            continue
        kde = gaussian_kde(vals)
        density = kde(x_grid)
        ax.plot(x_grid, density, label=label, color=color_map[condition])

    ax.set_xlabel(intensity_unit_label(phosprot_values_are_centred(kind)))
    ax.set_ylabel("Density")
    if header:
        # "ratio to site median" on a centred phosprot matrix: the title names
        # what the axis measures.
        quantity = "ratio to site median" if phosprot_values_are_centred(kind) else "intensity"
        ax.set_title(f"Distribution of mean {quantity} per condition (log2)")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        apply_advanced_axes(ax, advanced)
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        apply_advanced_axes(ax, advanced)
        plt.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


def _peptide_coverage_data(include_id=False, quantity_column=None, level="peptide"):
    from app.services.peptide_tools import (
        _sample_rename_map,
        get_peptide_frame,
    )

    if level not in {"peptide", "precursor"}:
        raise ValueError("Coverage level must be peptide or precursor.")
    frame = get_peptide_frame()
    file_col = peptide_file_column(frame)
    if level == "precursor":
        seq_col = peptide_precursor_column(frame)
    else:
        seq_col = peptide_sequence_column(frame)
    quantity_col = resolve_peptide_quantity_column(frame, requested=quantity_column)
    meta = _peptide_coverage_metadata(frame, include_id=include_id)

    pivot = frame.pivot_table(
        index=seq_col,
        columns=file_col,
        values=quantity_col,
        aggfunc="max",
    )
    if pivot.empty:
        raise ValueError("No peptide entries are available for coverage plotting.")

    pivot = raw_zero_to_nan(pivot, list(pivot.columns))
    labels = meta["label"].astype(str).tolist()
    rename_map = _sample_rename_map(
        pivot.columns, meta.rename(columns={"label": "new_sample"}), seq_col
    )
    pivot = pivot[list(rename_map)].rename(columns=rename_map)
    selected = [label for label in labels if label in pivot.columns]
    if not selected:
        raise ValueError("Peptide metadata does not match peptide sample columns.")

    data_filtered = pivot[selected].copy()
    data_filtered.attrs["quantity_column"] = quantity_col
    data_filtered.attrs["feature_column"] = seq_col
    return data_filtered, meta


def summarize_peptide_coverage(data_filtered, meta):
    selected = list(data_filtered.columns)
    summary = data_filtered.notna().sum(axis=0).reset_index()
    summary.columns = ["Sample", "Value"]
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=selected, ordered=True)
    summary = summary.sort_values("Sample")
    # Reference line: features quantified in at least one selected sample -- the
    # union of the bars, as on the protein coverage plot (_feature_context).
    # The pivot row count also holds sequences that were identified but never
    # quantified, or quantified only in runs outside the annotation.
    peptides_count = int(data_filtered.notna().any(axis=1).sum())

    return summary, peptides_count, meta


def _peptide_coverage_summary(include_id=False, quantity_column=None, level="peptide"):
    return summarize_peptide_coverage(*_peptide_coverage_data(include_id, quantity_column, level))


def qc_peptide_coverage_plot(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
    quantity_column: str | None = None,
    level: str = "peptide",
    reference_line: bool = True,
) -> bytes:
    from matplotlib.patches import Rectangle

    plt = _get_plt()
    summary, peptides_count, meta = _peptide_coverage_summary(include_id, quantity_column, level)
    selected = summary["Sample"].astype(str).tolist()

    conditions = meta["condition"].astype(str).dropna().tolist()
    ordered_conditions = list(dict.fromkeys(conditions))
    color_map = advanced_condition_colors("protein", plt, ordered_conditions, advanced)
    sample_to_condition = dict(zip(meta["label"].astype(str), meta["condition"].astype(str)))
    bar_colors = [
        color_map.get(sample_to_condition.get(str(sample), ""), "#1f77b4")
        for sample in summary["Sample"].astype(str).tolist()
    ]

    fig, ax = _make_fig(plt, width_cm, height_cm)
    ax.bar(range(len(summary)), summary["Value"].to_numpy(dtype=float), color=bar_colors)
    line = resolve_reference_line(advanced, color="red")
    if reference_line and line.visible:
        ax.axhline(y=peptides_count, **line.matplotlib())
    if header:
        ax.set_title(f"{level.capitalize()}s per sample")
    ax.set_ylabel(f"Number of {level}s")
    ax.set_xlabel("Sample")
    ax.set_xticks(range(len(summary)))
    ax.set_xticklabels(
        [
            advanced_label(sample, advanced, "sampleLabels", raw_sample)
            for sample, raw_sample in zip(summary["Sample"].astype(str).tolist(), selected)
        ],
        rotation=90,
    )

    if legend and ordered_conditions:
        handles = [Rectangle((0, 0), 1, 1, color=color_map[condition]) for condition in ordered_conditions]
        labels = [advanced_label(condition, advanced, "conditionLabels") for condition in ordered_conditions]
        ax.legend(handles, labels, title="Condition", bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")

    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _median_label_y(ax, median: float) -> float:
    """Where the median's number goes: a fixed step above the line.

    `median * 1.02` only worked for large positive values. Centred data has
    medians near zero (the text sat on the line) or negative (the text moved
    *down*, into the box). A step of 2 % of the axis span reads the same for
    any value, and matches the R plot's `pos = 3`.
    """
    low, high = ax.get_ylim()
    return float(median) + 0.02 * (high - low)


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
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Patch

    plt = _get_plt()
    frame = log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    conditions = meta["condition"].astype(str).dropna().unique().tolist()
    color_map = advanced_condition_colors(kind, plt, conditions, advanced)
    box_border_color = advanced_text(advanced, "boxBorderColor") or "black"
    box_median_color = advanced_text(advanced, "boxMedianColor") or "firebrick"
    box_outlier_color = advanced_text(advanced, "boxOutlierColor") or "red"
    box_outlier_edge_color = advanced_text(advanced, "boxOutlierEdgeColor") or "black"
    box_outlier_size = max(1.0, advanced_number(advanced, "boxOutlierSize", 5.0))
    boxprops = dict(linewidth=1.5, color=box_border_color)
    whiskerprops = dict(linewidth=1.5, color=box_border_color)
    capprops = dict(linewidth=1.5, color=box_border_color)
    medianprops = dict(linewidth=2.5, color=box_median_color)
    flierprops = (
        dict(
            marker="o",
            markerfacecolor=box_outlier_color,
            markeredgecolor=box_outlier_edge_color,
            markersize=box_outlier_size,
            linestyle="none",
        )
        if outliers
        else dict(marker="")
    )

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

        bp = ax.boxplot(
            grouped_data,
            patch_artist=True,
            showfliers=outliers,
            boxprops=boxprops,
            whiskerprops=whiskerprops,
            capprops=capprops,
            medianprops=medianprops,
            flierprops=flierprops,
        )
        sample_colors = [color_map[str(c)] for c in meta["condition"].tolist()]
        for patch, color in zip(bp["boxes"], sample_colors):
            patch.set_facecolor(color)
            patch.set_edgecolor(box_border_color)

        if text:
            medians = [np.median(g) if len(g) > 0 else np.nan for g in grouped_data]
            for i, median in enumerate(medians):
                if np.isnan(median):
                    continue
                x_pos, y_pos = i + 1, _median_label_y(ax, median)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{median:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=advanced_label_size(advanced, text_size),
                    rotation=0,
                    color="black",
                    fontweight="bold",
                )

        ax.set_xticks(range(1, len(samples) + 1))
        ax.set_xticklabels(
            [
                rename_composite_sample_label(sample, raw_sample, condition, advanced)
                for sample, raw_sample, condition in zip(
                    samples,
                    meta["sample"].astype(str).tolist(),
                    meta["condition"].astype(str).tolist(),
                )
            ],
            rotation=90,
            ha="center",
        )
        ax.set_xlabel("Sample")  # Mean mode says "Condition"; this axis said nothing.
        ax.set_ylabel(intensity_unit_label(phosprot_values_are_centred(kind)))
        if header:
            quantity = "ratio-to-site-median" if phosprot_values_are_centred(kind) else "intensity"
            ax.set_title(f"Measured {quantity} values (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor=box_border_color, label=advanced_label(c, advanced, "conditionLabels"))
                for c in conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=advanced_anchor(ax, advanced, 1, 0.5))
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
            patch.set_edgecolor(box_border_color)

        if text:
            for pos, med in zip(positions, medians):
                x_pos, y_pos = pos, _median_label_y(ax, med)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{med:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=advanced_label_size(advanced, text_size),
                    color="black",
                    rotation=0,
                    fontweight="bold",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels([advanced_label(condition, advanced, "conditionLabels") for condition in valid_conditions])
        ax.set_xlabel("Condition")
        ax.set_ylabel(intensity_unit_label(phosprot_values_are_centred(kind)))
        if header:
            quantity = "ratio to site median" if phosprot_values_are_centred(kind) else "intensity"
            ax.set_title(f"Mean {quantity} per condition (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor=box_border_color, label=advanced_label(c, advanced, "conditionLabels"))
                for c in valid_conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=advanced_anchor(ax, advanced, 1, 0.5))
            apply_advanced_axes(ax, advanced)
            plt.tight_layout(rect=[0, 0, 0.85, 1])

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        apply_advanced_axes(ax, advanced)
        plt.tight_layout()
    elif str(mode).lower() == "single":
        apply_advanced_axes(ax, advanced)

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
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Patch

    plt = _get_plt()
    frame = linear_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = raw_zero_to_nan(frame, sample_columns)[sample_columns]
    cvs = condition_cvs(numeric, meta)
    valid_conditions = [condition for condition, _ in cvs]
    cv_data = [cv.to_numpy(dtype=float) for _, cv in cvs]

    if not cv_data:
        raise ValueError("No numeric values available for CV plot.")

    color_map = advanced_condition_colors(kind, plt, valid_conditions, advanced)
    box_border_color = advanced_text(advanced, "boxBorderColor") or "black"
    box_median_color = advanced_text(advanced, "boxMedianColor") or "firebrick"
    box_outlier_color = advanced_text(advanced, "boxOutlierColor") or "red"
    box_outlier_edge_color = advanced_text(advanced, "boxOutlierEdgeColor") or "black"
    box_outlier_size = max(1.0, advanced_number(advanced, "boxOutlierSize", 5.0))
    fig, ax = _make_fig(plt, width_cm, height_cm)
    boxprops = dict(linewidth=1.5, color=box_border_color)
    whiskerprops = dict(linewidth=1.5, color=box_border_color)
    capprops = dict(linewidth=1.5, color=box_border_color)
    medianprops = dict(linewidth=2.5, color=box_median_color)
    flierprops = (
        dict(
            marker="o",
            markerfacecolor=box_outlier_color,
            markeredgecolor=box_outlier_edge_color,
            markersize=box_outlier_size,
            linestyle="none",
        )
        if outliers
        else dict(marker="")
    )
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
        patch.set_edgecolor(box_border_color)

    if text:
        for i, vals in enumerate(cv_data, start=1):
            med = float(np.median(vals))
            x_pos, y_pos = i, med
            ax.text(x_pos, y_pos, f"{med:.2f}", ha="center", va="bottom", fontsize=advanced_label_size(advanced, text_size), fontweight="bold", color="black")

    ax.set_xticks(positions)
    ax.set_xticklabels([advanced_label(condition, advanced, "conditionLabels") for condition in valid_conditions])
    ax.set_xlabel("Condition")
    ax.set_ylabel("Coefficient of Variation (%)")
    if header:
        ax.set_title("Coefficient of Variation")
    else:
        ax.set_title("")

    if legend:
        legend_handles = [
            Patch(facecolor=color_map[c], edgecolor=box_border_color, label=advanced_label(c, advanced, "conditionLabels"))
            for c in valid_conditions
        ]
        ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=advanced_anchor(ax, advanced, 1, 0.5))
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _pca_feature_matrix(numeric: pd.DataFrame, *, n_components: int) -> pd.DataFrame:
    """Complete features only -- the same rule the clustering paths apply.

    A projection is undefined for a feature missing in any sample, so those are
    dropped. `qc_pca_feature_summary` reports how many, and the interface shows
    it beneath the plot; see clustering_tools.completeness_message.
    """
    complete = numeric.dropna()
    if complete.shape[0] < n_components:
        raise ValueError(
            "PCA cannot be computed because only "
            f"{complete.shape[0]} of {numeric.shape[0]} features are observed in all samples; "
            "the missingness is too high. Run Imputation successfully and select 'Imputed Data' "
            "in the PCA controls, or impute the matrix before calling a PCA function."
        )
    return complete


def _small_sample_notice(method: str, samples: int, umap_n_neighbors: float, tsne_perplexity: float) -> str | None:
    """Say when UMAP or t-SNE settings exceed what this many samples can support.

    Both methods describe local neighbourhoods. UMAP with n_neighbors at or
    above the sample count treats every sample as a neighbour of every other,
    and t-SNE's perplexity has to be lowered below the sample count, so with a
    handful of samples their layouts carry little beyond what PCA shows.
    """
    key = str(method or "PCA").strip().lower()
    if key == "umap" and int(umap_n_neighbors) >= samples:
        return (
            f"UMAP n_neighbors is {int(umap_n_neighbors)} but there are only {samples} samples, so every "
            "sample counts as a neighbour of every other and the layout says little about local structure. "
            f"Use n_neighbors of at most {samples - 1}, or PCA."
        )
    if key in {"t-sne", "tsne", "t_sne"} and float(tsne_perplexity) > samples - 1:
        return (
            f"t-SNE perplexity {float(tsne_perplexity):g} was lowered to {max(1, samples - 1)} because there "
            f"are only {samples} samples. With so few samples the layout carries little beyond what PCA shows."
        )
    return None


def qc_pca_feature_summary(
    kind: AnnotationKind,
    data_source: str = "data",
    plot_dim: str = "2D",
    *,
    add_ellipses: bool = False,
    method: str = "PCA",
    scaling: str = "auto",
    color_by: str = "Condition",
    cluster_method: str = "None",
    cluster_count: int = 3,
    dbscan_eps_factor: float = 0.5,
    dbscan_min_samples: int = 2,
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    random_state: int = 42,
) -> dict[str, object]:
    """How many features the PCA projection is actually built from.

    Dimensionality reduction drops any feature with a missing value, so the
    projection can rest on a small and abundance-biased subset without that
    being visible anywhere. Surfaced so the UI can state it.

    With ellipses on, this also names the groups that cannot have one. The
    figure never says so itself -- a plot taken out of the tool should not carry
    a caption about how the tool drew it -- so the notice under it is the only
    place that can, and it needs the same projection the figure was drawn from.
    """
    # Checked before anything is computed: the ellipse notice below swallows its
    # own failures, so a typo here would otherwise pass unremarked.
    resolve_cluster_method(cluster_method)
    _, frame, _ = select_matrix(kind, data_source)
    sample_columns = _get_sample_columns(kind, frame)
    if len(sample_columns) < 2:
        raise ValueError("At least two sample columns are required for dimensionality reduction.")

    numeric = (
        frame[sample_columns]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    n_components = 3 if str(plot_dim).upper() == "3D" else 2
    total = int(numeric.shape[0])
    complete = int(numeric.dropna().shape[0])
    complete_matrix = numeric.dropna()
    variable = int((complete_matrix.var(axis=1) > 0).sum()) if not complete_matrix.empty else 0
    dbscan: dict[str, float] | None = None
    if resolve_cluster_method(cluster_method) == "dbscan":
        try:
            scores, _, axis_prefix = _pca_projection(
                kind,
                data_source=data_source,
                plot_dim=plot_dim,
                method=method,
                umap_n_neighbors=int(umap_n_neighbors),
                umap_min_dist=float(umap_min_dist),
                tsne_perplexity=float(tsne_perplexity),
                tsne_learning_rate=float(tsne_learning_rate),
                random_state=int(random_state),
                scaling=scaling,
            )
            component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]
            eps, median = dbscan_effective_eps(
                scores[component_cols].to_numpy(dtype=float), dbscan_eps_factor
            )
            dbscan = {
                "epsFactor": float(max(1e-6, float(dbscan_eps_factor))),
                "medianSampleDistance": float(median),
                "epsEffective": float(eps),
            }
        except Exception:  # noqa: BLE001 - the notice must never break the summary
            dbscan = None
    return {
        "dbscan": dbscan,
        "smallSampleNotice": _small_sample_notice(
            method, len(sample_columns), umap_n_neighbors, tsne_perplexity
        ),
        "ellipseSkippedGroups": (
            _groups_without_an_ellipse(
                kind,
                data_source=data_source,
                plot_dim=plot_dim,
                method=method,
                scaling=scaling,
                color_by=color_by,
                cluster_method=cluster_method,
                cluster_count=cluster_count,
                dbscan_eps_factor=dbscan_eps_factor,
                dbscan_min_samples=dbscan_min_samples,
                umap_n_neighbors=umap_n_neighbors,
                umap_min_dist=umap_min_dist,
                tsne_perplexity=tsne_perplexity,
                tsne_learning_rate=tsne_learning_rate,
                random_state=random_state,
            )
            if add_ellipses and str(plot_dim).upper() != "3D"
            else []
        ),
        "featuresTotal": total,
        "featuresComplete": complete,
        "featuresUsed": variable,
        "featuresRequired": n_components,
    }


def _pca_projection(
    kind: AnnotationKind,
    data_source: str = "data",
    plot_dim: str = "2D",
    method: str = "PCA",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    random_state: int = 42,
    scaling: str = "auto",
) -> tuple[pd.DataFrame, np.ndarray | None, str]:
    _, frame, _ = select_matrix(kind, data_source)
    sample_columns = _get_sample_columns(kind, frame)
    if len(sample_columns) < 2:
        raise ValueError("At least two sample columns are required for dimensionality reduction.")

    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    n_components = 3 if str(plot_dim).upper() == "3D" else 2
    data_filtered = _pca_feature_matrix(numeric, n_components=n_components)

    transposed_expr = data_filtered.T
    transposed_expr = transposed_expr.loc[:, transposed_expr.var(axis=0) > 0]
    if transposed_expr.empty:
        raise ValueError("All features have zero variance; dimensionality reduction cannot be computed.")

    if transposed_expr.shape[0] < n_components:
        raise ValueError(f"Need at least {n_components} samples for {n_components}D projection.")

    method_key = str(method or "PCA").strip().lower()
    if method_key == "pca" and transposed_expr.shape[1] < n_components:
        raise ValueError(f"Need at least {n_components} non-constant features for {n_components}D PCA.")
    x = transposed_expr.values.astype(float)
    x_centered = x - x.mean(axis=0, keepdims=True)
    # Sample SD (n-1), as R's prcomp(scale. = TRUE) and the heatmap z-scores use.
    # Until 2026-10-02 this was the n SD, so scaled scores differed from R by
    # sqrt(n / (n - 1)); the shape and explained variance were the same.
    x_std = x_centered.std(axis=0, ddof=1, keepdims=True) if x.shape[0] > 1 else np.ones((1, x.shape[1]))
    x_std[~np.isfinite(x_std) | (x_std == 0)] = 1.0
    resolved_scaling = resolve_feature_scaling(scaling, method=method_key)
    projection_input = x_centered if resolved_scaling == "centered" else x_centered / x_std

    explained: np.ndarray | None = None
    axis_prefix = "PC"

    if method_key == "pca":
        u, s, _ = np.linalg.svd(projection_input, full_matrices=False)
        scores = u[:, :n_components] * s[:n_components]
        explained = (s ** 2) / max(float(np.sum(s ** 2)), 1e-12) * 100.0
        axis_prefix = "PC"
    elif method_key == "umap":
        try:
            import umap
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "umap-learn is required for UMAP. Install it with: pip install umap-learn"
            ) from exc
        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=max(2, int(umap_n_neighbors)),
            min_dist=max(0.0, float(umap_min_dist)),
            random_state=int(random_state),
        )
        scores = reducer.fit_transform(projection_input)
        axis_prefix = "UMAP"
    elif method_key in {"t-sne", "tsne", "t_sne"}:
        try:
            from sklearn.manifold import TSNE
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "scikit-learn is required for t-SNE. Install it with: pip install scikit-learn"
            ) from exc

        max_perplexity = max(1.0, float(transposed_expr.shape[0] - 1))
        effective_perplexity = min(max(1.0, float(tsne_perplexity)), max_perplexity)
        tsne = TSNE(
            n_components=n_components,
            perplexity=effective_perplexity,
            learning_rate=max(10.0, float(tsne_learning_rate)),
            init="pca",
            random_state=int(random_state),
            method="barnes_hut",
        )
        scores = tsne.fit_transform(projection_input)
        axis_prefix = "t-SNE"
    else:
        raise ValueError("Unsupported dimensionality-reduction method. Use PCA, UMAP, or t-SNE.")

    pcs = [f"{axis_prefix}{i + 1}" for i in range(n_components)]
    pca_scores = pd.DataFrame(scores, columns=pcs)
    pca_scores["sample"] = transposed_expr.index.astype(str)
    condition_map = meta.set_index("sample")["condition"].astype(str).to_dict()
    pca_scores["condition"] = pca_scores["sample"].map(condition_map).fillna("sample")
    return pca_scores, explained, axis_prefix


_CLUSTER_METHODS = frozenset(
    {"none", "", "off", "kmeans", "agglomerative", "hierarchical", "dbscan"}
)


def resolve_cluster_method(cluster_method: str) -> str:
    """The clustering method, lowercased, or a refusal.

    One list, checked by everything that takes the parameter. A caller that
    validates by trying to cluster would let a typo through wherever the
    clustering itself is skipped -- which is exactly what the ellipse notice
    does -- and the user would see a figure grouped by something they did not
    ask for, with no error.
    """
    method_key = str(cluster_method or "None").strip().lower()
    if method_key not in _CLUSTER_METHODS:
        raise ValueError(
            "Unsupported clustering method. Use None, KMeans, Agglomerative, or DBSCAN."
        )
    return method_key


def median_sample_distance(embedding: np.ndarray) -> float:
    """Median Euclidean distance between all pairs of samples in the embedding."""
    points = np.asarray(embedding, dtype=float)
    if points.ndim != 2 or points.shape[0] < 2:
        return 0.0
    diffs = points[:, None, :] - points[None, :, :]
    distances = np.sqrt((diffs**2).sum(axis=2))
    upper = distances[np.triu_indices(points.shape[0], k=1)]
    upper = upper[np.isfinite(upper)]
    if upper.size == 0:
        return 0.0
    return float(np.median(upper))


def dbscan_effective_eps(embedding: np.ndarray, factor: float) -> tuple[float, float]:
    """The DBSCAN neighbourhood radius actually used, and the distance it scales.

    `factor` is relative: eps = factor x median pairwise sample distance in the
    projected coordinates. PC scores of a proteome span tens of log2 units,
    UMAP a handful, t-SNE tens -- an absolute radius means something different
    on each, and the old absolute default of 0.5 labelled every sample "Noise"
    on any real projection. Half the typical inter-sample distance is a radius
    the user can reason about before seeing the plot. When the median is zero
    or undefined (fewer than two samples, all samples coincident) the factor is
    used as an absolute radius so DBSCAN still runs.
    """
    factor_value = max(1e-6, float(factor))
    median = median_sample_distance(embedding)
    if not np.isfinite(median) or median <= 0:
        return factor_value, 0.0
    return factor_value * median, median


def _compute_cluster_labels(
    embedding: np.ndarray,
    *,
    cluster_method: str = "None",
    cluster_count: int = 3,
    dbscan_eps_factor: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
) -> np.ndarray | None:
    method_key = resolve_cluster_method(cluster_method)
    if method_key in {"none", "", "off"}:
        return None
    if embedding.shape[0] < 2:
        return None

    try:
        from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "scikit-learn is required for clustering. Install it with: pip install scikit-learn"
        ) from exc

    if method_key == "kmeans":
        k = min(max(2, int(cluster_count)), embedding.shape[0])
        model = KMeans(n_clusters=k, random_state=int(random_state), n_init=10)
        return model.fit_predict(embedding)
    if method_key in {"agglomerative", "hierarchical"}:
        k = min(max(2, int(cluster_count)), embedding.shape[0])
        model = AgglomerativeClustering(n_clusters=k)
        return model.fit_predict(embedding)
    if method_key == "dbscan":
        eps, _median = dbscan_effective_eps(embedding, dbscan_eps_factor)
        model = DBSCAN(
            eps=eps,
            min_samples=max(1, int(dbscan_min_samples)),
        )
        return model.fit_predict(embedding)

    raise ValueError("Unsupported clustering method. Use None, KMeans, Agglomerative, or DBSCAN.")


def _cluster_display_label(label: int) -> str:
    if int(label) == -1:
        return "Noise"
    return f"Cluster {int(label) + 1}"


def _groups_without_an_ellipse(
    kind: AnnotationKind,
    *,
    data_source: str,
    plot_dim: str,
    method: str,
    scaling: str,
    color_by: str,
    cluster_method: str,
    cluster_count: int,
    dbscan_eps_factor: float,
    dbscan_min_samples: int,
    umap_n_neighbors: float,
    umap_min_dist: float,
    tsne_perplexity: float,
    tsne_learning_rate: float,
    random_state: int,
) -> list[str]:
    """The groups the 2D figure cannot draw an ellipse for.

    It repeats the projection and the grouping exactly as `qc_pca_plot` does,
    because an ellipse depends on where the points land: the same samples under
    a different method or scaling can gain or lose their spread. A failure here
    is not worth a 500 -- the notice is an extra, and the figure is already on
    screen -- so anything that goes wrong is reported as "no groups to name".
    """
    try:
        pca_scores, _, axis_prefix = _pca_projection(
            kind,
            data_source=data_source,
            plot_dim=plot_dim,
            method=method,
            umap_n_neighbors=int(umap_n_neighbors),
            umap_min_dist=float(umap_min_dist),
            tsne_perplexity=float(tsne_perplexity),
            tsne_learning_rate=float(tsne_learning_rate),
            random_state=int(random_state),
            scaling=scaling,
        )
        component_cols = [f"{axis_prefix}1", f"{axis_prefix}2"]
        cluster_labels = _compute_cluster_labels(
            pca_scores[component_cols].to_numpy(dtype=float),
            cluster_method=cluster_method,
            cluster_count=cluster_count,
            dbscan_eps_factor=dbscan_eps_factor,
            dbscan_min_samples=dbscan_min_samples,
            random_state=random_state,
        )
        if cluster_labels is not None:
            pca_scores["cluster"] = [_cluster_display_label(value) for value in cluster_labels]
        group_col = (
            "cluster"
            if str(color_by or "Condition").strip().lower() == "cluster"
            and cluster_labels is not None
            else "condition"
        )
        return [
            str(group)
            for group in pca_scores[group_col].astype(str).dropna().unique().tolist()
            if fitted_group_ellipse(
                pca_scores.loc[pca_scores[group_col] == group, component_cols].to_numpy()
            )
            is None
        ]
    except Exception:  # noqa: BLE001 - the notice must never break the summary
        return []


def qc_pca_plot(
    kind: AnnotationKind,
    data_source: str = "data",
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 5,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps_factor: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    scaling: str = "auto",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Ellipse

    plt = _get_plt()
    pca_scores, explained, axis_prefix = _pca_projection(
        kind,
        data_source=data_source,
        plot_dim=plot_dim,
        method=method,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        random_state=random_state,
        scaling=scaling,
    )
    n_components = 3 if str(plot_dim).upper() == "3D" else 2
    component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]

    cluster_labels = _compute_cluster_labels(
        pca_scores[component_cols].to_numpy(dtype=float),
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        dbscan_eps_factor=dbscan_eps_factor,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
    )
    if cluster_labels is not None:
        pca_scores["cluster"] = [_cluster_display_label(value) for value in cluster_labels]

    color_by_key = str(color_by or "Condition").strip().lower()
    group_col = (
        "cluster"
        if color_by_key == "cluster" and cluster_labels is not None
        else "condition"
    )

    groups = pca_scores[group_col].astype(str).dropna().unique().tolist()
    color_map = advanced_condition_colors(kind, plt, groups, advanced)
    method_name = "t-SNE" if str(method).strip().lower() in {"t-sne", "tsne", "t_sne"} else str(method).strip().upper()

    if n_components == 3:
        fig = plt.figure(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
        ax = fig.add_subplot(111, projection="3d")
        for group in groups:
            subset = pca_scores[pca_scores[group_col] == group]
            ax.scatter(
                subset[component_cols[0]],
                subset[component_cols[1]],
                subset[component_cols[2]],
                label=advanced_label(group, advanced, "conditionLabels"),
                **marker_style(
                    advanced,
                    size=pca_default_size(dot_size),
                    alpha=0.7,
                    group=group,
                    color=color_map[group],
                ),
            )
        if explained is not None and axis_prefix == "PC":
            ax.set_xlabel(f"{component_cols[0]} - {explained[0]:.2f}%")
            ax.set_ylabel(f"{component_cols[1]} - {explained[1]:.2f}%")
            ax.set_zlabel(f"{component_cols[2]} - {explained[2]:.2f}%")
        else:
            ax.set_xlabel(component_cols[0])
            ax.set_ylabel(component_cols[1])
            ax.set_zlabel(component_cols[2])
        if header:
            ax.set_title(f"3D {method_name} Plot")
        else:
            ax.set_title("")
        if legend:
            ax.legend(
                title="Cluster" if group_col == "cluster" else "Condition",
                bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1),
                loc="upper left",
            )
    else:
        fig, ax = _make_fig(plt, width_cm, height_cm)
        for group in groups:
            subset = pca_scores[pca_scores[group_col] == group]
            ax.scatter(
                subset[component_cols[0]],
                subset[component_cols[1]],
                label=advanced_label(group, advanced, "conditionLabels"),
                **marker_style(
                    advanced,
                    size=pca_default_size(dot_size),
                    alpha=0.7,
                    group=group,
                    color=color_map[group],
                ),
            )
            fit = (
                fitted_group_ellipse(subset[[component_cols[0], component_cols[1]]].to_numpy())
                if add_ellipses
                else None
            )
            if fit is not None:
                center, axes, angle = fit
                ellipse = Ellipse(
                    xy=center,
                    width=2 * axes[0],
                    height=2 * axes[1],
                    angle=angle,
                    facecolor=color_map[group],
                    alpha=0.15,
                    edgecolor=color_map[group],
                    lw=1,
                )
                ax.add_patch(ellipse)

        if explained is not None and axis_prefix == "PC":
            ax.set_xlabel(f"{component_cols[0]} - {explained[0]:.2f}% variance")
            ax.set_ylabel(f"{component_cols[1]} - {explained[1]:.2f}% variance")
        else:
            ax.set_xlabel(component_cols[0])
            ax.set_ylabel(component_cols[1])
        if header:
            ax.set_title(f"{method_name} Plot")
        else:
            ax.set_title("")
        if legend:
            ax.legend(
                title="Cluster" if group_col == "cluster" else "Condition",
                bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1),
                loc="upper left",
            )

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def qc_pca_interactive_html(
    kind: AnnotationKind,
    data_source: str = "data",
    header: bool = True,
    legend: bool = True,
    plot_dim: str = "2D",
    method: str = "PCA",
    add_ellipses: bool = False,
    dot_size: int = 8,
    cluster_method: str = "None",
    cluster_count: int = 3,
    color_by: str = "Condition",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    dbscan_eps_factor: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    scaling: str = "auto",
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict[str, Any] | None = None,
) -> str:
    px, go = _get_plotly()
    pca_scores, explained, axis_prefix = _pca_projection(
        kind,
        data_source=data_source,
        plot_dim=plot_dim,
        method=method,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        random_state=random_state,
        scaling=scaling,
    )
    plot_3d = str(plot_dim).upper() == "3D"
    n_components = 3 if plot_3d else 2
    component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]

    height_px = _cm_to_px(height_cm)
    cluster_labels = _compute_cluster_labels(
        pca_scores[component_cols].to_numpy(dtype=float),
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        dbscan_eps_factor=dbscan_eps_factor,
        dbscan_min_samples=dbscan_min_samples,
        random_state=random_state,
    )
    if cluster_labels is not None:
        pca_scores["cluster"] = [_cluster_display_label(value) for value in cluster_labels]

    color_by_key = str(color_by or "Condition").strip().lower()
    color_col = (
        "cluster"
        if color_by_key == "cluster" and cluster_labels is not None
        else "condition"
    )
    groups = pca_scores[color_col].astype(str).dropna().unique().tolist()
    color_map = advanced_condition_colors(kind, None, groups, advanced)
    display_col = f"{color_col}_display"
    pca_scores[display_col] = pca_scores[color_col].astype(str).map(
        lambda value: advanced_label(value, advanced, "conditionLabels")
    )
    display_color_map = {
        advanced_label(group, advanced, "conditionLabels"): color_map[group]
        for group in groups
    }
    method_name = "t-SNE" if str(method).strip().lower() in {"t-sne", "tsne", "t_sne"} else str(method).strip().upper()

    # Hover text reads "Sample", "Condition", "Cluster": the data columns keep
    # their names, the labels map them for the reader. The coloured column is
    # the (possibly renamed) condition or cluster, so the raw one is not
    # repeated beneath it.
    hover_data = {"sample": True, "condition": color_col != "condition"}
    if cluster_labels is not None:
        hover_data["cluster"] = color_col != "cluster"
    hover_labels = {
        "sample": "Sample", "condition": "Condition", "cluster": "Cluster",
        display_col: "Cluster" if color_col == "cluster" else "Condition",
    }

    if plot_3d:
        fig = px.scatter_3d(
            pca_scores,
            x=component_cols[0],
            y=component_cols[1],
            z=component_cols[2],
            color=display_col,
            color_discrete_map=display_color_map,
            hover_data=hover_data,
            labels=hover_labels,
            opacity=0.85,
        )
        apply_plotly_group_markers(
            fig,
            advanced,
            size=pca_default_size(dot_size),
            alpha=0.85,
            display_to_group={
                advanced_label(group, advanced, "conditionLabels"): group
                for group in groups
            },
            colors=color_map,
        )
        if explained is not None and axis_prefix == "PC":
            x_title = f"{component_cols[0]} - {explained[0]:.2f}%"
            y_title = f"{component_cols[1]} - {explained[1]:.2f}%"
            z_title = f"{component_cols[2]} - {explained[2]:.2f}%"
        else:
            x_title = component_cols[0]
            y_title = component_cols[1]
            z_title = component_cols[2]
        fig.update_layout(
            height=height_px,
            autosize=True,
            showlegend=legend,
            title=f"3D {method_name} Plot" if header else None,
            scene=dict(
                xaxis=dict(title=x_title),
                yaxis=dict(title=y_title),
                zaxis=dict(title=z_title),
                # A cube whatever the score ranges: with the default "auto"
                # the box stretched along the widest component and the figure
                # changed its height from dataset to dataset.
                aspectmode="cube",
            ),
            legend_title_text="Cluster" if color_col == "cluster" else "Condition",
        )
        scene_overrides: dict[str, Any] = {}
        x_override = advanced_element_text(advanced, "xLabelElement")
        y_override = advanced_element_text(advanced, "yLabelElement")
        if x_override is not None:
            scene_overrides["xaxis_title"] = x_override
        if y_override is not None:
            scene_overrides["yaxis_title"] = y_override
        if scene_overrides:
            fig.update_layout(scene=scene_overrides)
        fig.update_layout(**advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))
        return _plotly_html(fig)

    fig = px.scatter(
        pca_scores,
        x=component_cols[0],
        y=component_cols[1],
        color=display_col,
        color_discrete_map=display_color_map,
        hover_data=hover_data,
        labels=hover_labels,
        opacity=0.85,
    )
    apply_plotly_group_markers(
        fig,
        advanced,
        size=pca_default_size(dot_size),
        alpha=0.85,
        display_to_group={
            advanced_label(group, advanced, "conditionLabels"): group for group in groups
        },
        colors=color_map,
    )
    if explained is not None and axis_prefix == "PC":
        x_title = f"{component_cols[0]} - {explained[0]:.2f}% variance"
        y_title = f"{component_cols[1]} - {explained[1]:.2f}% variance"
    else:
        x_title = component_cols[0]
        y_title = component_cols[1]
    fig.update_layout(
        height=height_px,
        autosize=True,
        showlegend=legend,
        title=f"{method_name} Plot" if header else None,
        xaxis=dict(title=x_title, zeroline=False),
        yaxis=dict(title=y_title, zeroline=False),
        legend_title_text="Cluster" if color_col == "cluster" else "Condition",
    )
    fig.update_layout(**advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))

    if add_ellipses:
        for group in groups:
            subset = pca_scores[pca_scores[color_col] == group]
            fit = fitted_group_ellipse(
                subset[[component_cols[0], component_cols[1]]].to_numpy()
            )
            if fit is None:
                continue
            center, axes, angle = fit
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
                    line=dict(width=1, color=color_map.get(group, "#6b7280")),
                    fillcolor=color_map.get(group, "#6b7280"),
                    showlegend=False,
                    hoverinfo="skip",
                    opacity=0.18,
                )
            )

    return _plotly_html(fig)


def _abundance_key_column(frame: pd.DataFrame, workflow: str, kind: AnnotationKind) -> str:
    if workflow == "Protein":
        candidates = ["ProteinNames", "Protein_group", "GeneNames"]
    elif workflow == "Phosphoprotein" or kind == "phosprot":
        candidates = ["Phosphoprotein", "Protein_group", "Gene_group", "ProteinNames"]
    else:
        candidates = ["PTM_Collapse_key", "Phosphosite"]

    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return str(frame.columns[0])


def _abundance_mean_intensities(
    kind: AnnotationKind,
) -> tuple[pd.DataFrame, list[str], str, str]:
    frame = linear_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError("No sample columns available for abundance plot.")

    _, _, _, workflow = _feature_context(frame)
    if workflow == "Feature":
        workflow = "Protein" if kind == "protein" else "Phosphosite"
    key_col = _abundance_key_column(frame, workflow, kind)
    sample_columns = [column for column in sample_columns if column in frame.columns and column != key_col]
    if not sample_columns:
        raise ValueError("No sample columns available for abundance plot.")

    frame = raw_zero_to_nan(frame, sample_columns)
    meta = _metadata_for_kind(kind, frame, sample_columns).copy()
    unique_conditions = meta["condition"].astype(str).dropna().unique().tolist()
    if not unique_conditions:
        raise ValueError("No conditions available for abundance plot.")

    data_filtered = frame[[key_col] + sample_columns].copy()
    key_values = data_filtered[key_col]
    if isinstance(key_values, pd.DataFrame):
        key_values = key_values.iloc[:, 0]
    mean_intensities = key_values.rename(key_col).to_frame()
    valid_conditions: list[str] = []
    for cond in unique_conditions:
        cols = [
            column
            for column in meta.loc[meta["condition"] == cond, "sample"].tolist()
            if column in data_filtered.columns and column != key_col
        ]
        if not cols:
            continue
        means = data_filtered[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
        # No pseudocount. The axis says log10 of the value, so the number has to
        # be log10 of the value: `log10(x + 1)` is up to 0.30 too high, which on
        # `robust_site_median` phosprot data -- ratios centred on 1 -- shifts
        # every point and compresses the curve's range by 40%. Zeros are already
        # NaN by `raw_zero_to_nan` above; anything else non-positive has no
        # logarithm and is dropped by the `dropna` below rather than plotted at
        # a value it does not have.
        mean_intensities[cond] = np.log10(means.where(means > 0))
        valid_conditions.append(cond)

    if not valid_conditions:
        raise ValueError("No conditions available for abundance plot.")

    mean_intensities = mean_intensities.dropna(subset=valid_conditions, how="all")

    return mean_intensities, valid_conditions, workflow, key_col


def _abundance_rank_frame(kind: AnnotationKind) -> tuple[pd.DataFrame, list[str], str]:
    mean_intensities, unique_conditions, workflow, key_col = _abundance_mean_intensities(kind)

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
    advanced: dict[str, Any] | None = None,
) -> bytes:
    plt = _get_plt()
    mean_intensities, unique_conditions, workflow, key_col = _abundance_mean_intensities(kind)

    color_map = advanced_condition_colors(kind, plt, unique_conditions, advanced)
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
            ax.scatter(
                subset["Rank"],
                subset["log10Intensity"],
                label=advanced_label(cond, advanced, "conditionLabels"),
                **marker_style(
                    advanced, size=2.3, alpha=1.0, group=cond, color=color_map[cond]
                ),
            )
    else:
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        values = mean_intensities[condition].dropna().sort_values(ascending=False).reset_index(drop=True)
        ranks = np.arange(1, len(values) + 1)
        ax.scatter(
            ranks,
            values.values,
            label=advanced_label(condition, advanced, "conditionLabels"),
            **marker_style(
                advanced,
                size=2.7,
                alpha=1.0,
                group=condition,
                color=color_map[condition],
            ),
        )

    ax.set_xlabel(f"{workflow} Rank")
    ax.set_ylabel(abundance_axis_label(workflow, phosprot_values_are_centred(kind)))
    if header:
        ax.set_title(f"Abundance plot - {workflow}")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        apply_advanced_axes(ax, advanced)
        fig.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        apply_advanced_axes(ax, advanced)
        fig.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


def qc_abundance_interactive_html(
    kind: AnnotationKind,
    condition: str = "All Conditions",
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict[str, Any] | None = None,
) -> str:
    px, _ = _get_plotly()
    long_intensities, unique_conditions, workflow = _abundance_rank_frame(kind)
    height_px = _cm_to_px(height_cm)

    if condition != "All Conditions":
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        long_intensities = long_intensities[long_intensities["Condition"] == condition]
    visible_conditions = long_intensities["Condition"].astype(str).dropna().unique().tolist()
    color_map = advanced_condition_colors(kind, None, visible_conditions, advanced)
    long_intensities = long_intensities.copy()
    long_intensities["ConditionDisplay"] = long_intensities["Condition"].astype(str).map(
        lambda value: advanced_label(value, advanced, "conditionLabels")
    )
    display_color_map = {
        advanced_label(condition, advanced, "conditionLabels"): color_map[condition]
        for condition in visible_conditions
    }

    fig = px.scatter(
        long_intensities,
        x="Rank",
        y="log10Intensity",
        color="ConditionDisplay",
        color_discrete_map=display_color_map,
        hover_data={"Feature": True, "Condition": False, "Rank": True, "log10Intensity": ":.4f"},
        labels={"ConditionDisplay": "Condition", "log10Intensity": "log10 intensity", "Rank": "Rank", "Feature": "Feature"},
        opacity=0.85,
    )
    apply_plotly_group_markers(
        fig,
        advanced,
        size=6,
        alpha=0.85,
        display_to_group={
            advanced_label(condition, advanced, "conditionLabels"): condition
            for condition in visible_conditions
        },
        colors=color_map,
    )
    fig.update_layout(
        height=height_px,
        autosize=True,
        showlegend=legend,
        title=f"Abundance plot - {workflow}" if header else None,
        xaxis_title=f"{workflow} Rank",
        yaxis_title=abundance_axis_label(workflow, phosprot_values_are_centred(kind)),
    )
    fig.update_layout(**advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))
    return _plotly_html(fig)



def correlation_matrix_mesh(ax, matrix, cmap, vmin, vmax):
    """The correlation matrix as one rectangle per cell, laid out as `matshow` lays it out.

    `matshow` draws the matrix as an image, so an SVG or PDF download held a
    bitmap: blurred when scaled, and not one shape per cell to edit. A mesh is
    vector in those formats and the same picture in a PNG. Row 0 is at the top,
    the cells are square and the column ticks are on top, as before.
    """
    values = np.ma.masked_invalid(np.asarray(matrix, dtype=float))
    rows, cols = values.shape
    mesh = ax.pcolormesh(
        np.arange(cols + 1) - 0.5,
        np.arange(rows + 1) - 0.5,
        values,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="flat",
        # Each cell's edge in its own colour: without it a vector viewer shows
        # hairline gaps between neighbouring cells.
        edgecolors="face",
        linewidth=0.0,
    )
    ax.set_xlim(-0.5, cols - 0.5)
    ax.set_ylim(rows - 0.5, -0.5)
    ax.set_aspect("equal")
    ax.xaxis.tick_top()
    return mesh

def qc_correlation_plot(
    kind: AnnotationKind,
    method: str = "Matrix",
    include_id: bool = False,
    full_range: bool = False,
    width_cm: float = 20,
    height_cm: float = 16,
    dpi: int = 400,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Ellipse

    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
        from scipy.spatial.distance import squareform

        has_scipy = True
    except ModuleNotFoundError:
        has_scipy = False

    plt = _get_plt()
    frame = log2_qc_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
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
    original_by_label = {str(label): str(sample) for sample, label in rename_map.items()}
    # The composite label a tick shows is `Condition_1`, so the condition rename
    # has to be applied to it as well; see rename_composite_sample_label.
    condition_by_label = {
        str(label): str(condition)
        for label, condition in zip(meta["new_sample"].tolist(), meta["condition"].astype(str).tolist())
    }
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
    incomplete = not np.isfinite(correlation_matrix.to_numpy()).all()
    if has_scipy and len(correlation_matrix) > 1 and not incomplete:
        distance_matrix = 1 - correlation_matrix
        distance_matrix = distance_matrix.clip(lower=0.0, upper=2.0)
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

    finite_correlations = ordered_corr.to_numpy()[np.isfinite(ordered_corr.to_numpy())]
    if full_range or finite_correlations.size == 0:
        vmin, vmax = -1.0, 1.0
    else:
        vmin = float(finite_correlations.min())
        vmax = float(finite_correlations.max())
        if math.isclose(vmin, vmax):
            vmin, vmax = -1.0, 1.0

    fig, ax = _make_fig(plt, width_cm, height_cm)
    color_map_options = {
        "coolwarm",
        "RdBu_r",
        "Spectral",
        "PiYG",
        "PRGn",
        "BrBG",
        "viridis",
        "cividis",
    }
    cmap_name = advanced_color_map(advanced, "coolwarm")
    if cmap_name not in color_map_options:
        cmap_name = "coolwarm"
    cmap = plt.get_cmap(cmap_name).with_extremes(bad="#eeeeee")
    color_norm = plt.Normalize(vmin=vmin, vmax=vmax)
    method_normalized = str(method).strip().lower()
    x_labels = [
        rename_composite_sample_label(
            str(label),
            original_by_label.get(str(label), ""),
            condition_by_label.get(str(label), ""),
            advanced,
        )
        for label in ordered_corr.columns.tolist()
    ]
    y_labels = [
        rename_composite_sample_label(
            str(label),
            original_by_label.get(str(label), ""),
            condition_by_label.get(str(label), ""),
            advanced,
        )
        for label in ordered_corr.index.tolist()
    ]
    if method_normalized == "matrix":
        cax = correlation_matrix_mesh(ax, ordered_corr, cmap, vmin, vmax)
        ax.set_xticks(range(len(ordered_corr.columns)))
        ax.set_yticks(range(len(ordered_corr.index)))
        ax.set_xticklabels(x_labels, rotation=90, ha="center", va="bottom", fontsize=7)
        ax.set_yticklabels(y_labels, fontsize=7)
        fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04, label="Pearson r (log2 intensities)")
    elif method_normalized == "ellipse":
        n = len(ordered_corr)
        ax.set_xlim(0, n)
        ax.set_ylim(0, n)
        ax.set_xticks(np.arange(n) + 0.5)
        ax.set_yticks(np.arange(n) + 0.5)
        ax.set_xticklabels(x_labels, rotation=90, ha="center", va="top", fontsize=7)
        ax.set_yticklabels(y_labels, fontsize=7)
        ax.invert_yaxis()

        for i in range(n):
            for j in range(n):
                r = float(ordered_corr.iloc[i, j])
                if not np.isfinite(r):
                    continue
                ellipse = Ellipse(
                    (j + 0.5, i + 0.5),
                    width=0.9,
                    height=0.9 * (1 - abs(r)),
                    # The y axis is inverted above, so a +45 degree patch would
                    # render as "\\"; -45 is what draws a positive correlation
                    # rising left to right, as the scatter it stands for would.
                    angle=-45 if r > 0 else 45,
                    facecolor=cmap(color_norm(r)),
                    alpha=0.6,
                )
                ax.add_patch(ellipse)

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=color_norm)
        fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04, label="Pearson r (log2 intensities)")
    else:
        raise ValueError("method must be 'Matrix' or 'Ellipse'")

    missing_rows, missing_cols = np.where(~np.isfinite(ordered_corr.to_numpy()))
    offset = 0.5 if method_normalized == "ellipse" else 0
    for i, j in zip(missing_rows, missing_cols):
        ax.text(j + offset, i + offset, "NA", ha="center", va="center", fontsize=7, color="#666666")
    ax.set_xlabel("Samples" + ("\nNA: correlation unavailable; clustering skipped (metadata order)" if incomplete else ""))
    ax.set_ylabel("Samples")
    # A title so the exported figure says what it shows; the advanced panel's
    # title switch and custom text still override it.
    ax.set_title(
        "Sample correlation (Pearson r, log2 intensities)"
        + (" \u2014 ellipse tilt: / positive, \\ negative; narrower = stronger" if method_normalized == "ellipse" else ""),
        fontsize=9,
    )
    apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)

# Each module caches its own renderers, the way table_functions and
# single_protein_tools already did. These were cached one layer up, by a facade
# in functions.py that forwarded to them; the facade is gone and the cache
# stays where the work is.
apply_cached_wrappers(
    globals(),
    [
        "imputation_before_plot",
        "imputation_overall_fit_plot",
        "imputation_after_plot",
        "distribution_qqnorm_plot",
        "qc_coverage_plot",
        "qc_peptide_coverage_plot",
        "qc_intensity_histogram_plot",
        "qc_boxplot_plot",
        "qc_cv_plot",
        "qc_pca_plot",
        "qc_pca_interactive_html",
        "qc_abundance_plot",
        "qc_abundance_interactive_html",
        "qc_correlation_plot",
    ],
)

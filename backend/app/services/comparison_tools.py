from __future__ import annotations


from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
    cm_to_px as _cm_to_px,
)


import numpy as np
import pandas as pd
from textwrap import fill


from app.schemas.annotation import AnnotationKind
from app.services.functions import (
    condition_mean,
    qc_matrix,
)
from app.services.plot_styling import (
    advanced_label,
    advanced_plotly_layout,
    apply_advanced_axes,
    advanced_color,
    marker_style,
    plotly_marker,
    resolve_reference_line,
)
from app.services.runtime_cache import apply_cached_wrappers
from app.services.plotting_common import get_plt as _get_plt, get_plotly_go as _get_plotly, plotly_html as _plotly_html, truncate_hover_text as _truncate_hover_text


def _rename_if_condition(label: str, mode: str, advanced: dict | None) -> str:
    """Apply the condition rename, but only when the label is a condition.

    This page draws either two samples or two conditions, and the axis carries
    whichever it was given. Renaming unconditionally would rewrite a sample name
    that happened to match a condition name.
    """
    if str(mode).strip().lower() in {"single", "sample"}:
        return str(label)
    return advanced_label(str(label), advanced, "conditionLabels")


def _legacy_area_as_diameter(dot_size: float) -> float:
    """The old correlation `dotSize`, which was an area, read as a diameter."""
    return max(1.0, float(dot_size)) ** 0.5


def _wrap_label(label: str, width_cm: float) -> str:
    return fill(label, width=max(10, int(width_cm * 3)),
                expand_tabs=False, replace_whitespace=False, drop_whitespace=False, break_on_hyphens=False)


def _get_venn():
    try:
        from matplotlib_venn import venn2, venn3

        return venn2, venn3
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib-venn is required for Venn diagrams. Install it with: pip install matplotlib-venn"
        ) from exc


def _analysis_context(
    kind: AnnotationKind,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Comparison is QC: it describes the samples as loaded, with no choice.

    A Venn of what each sample identified, and a correlation between two
    samples, are both statements about the data that arrived -- filtering or
    imputing first would remove the very thing being inspected (a Venn on
    imputed data has no missingness left to compare). Fixing it here also keeps
    the Pearson plots and the correlation heatmap on one matrix, which is what
    lets a reader compare them.
    """
    frame, meta = qc_matrix(kind)
    sample_columns = [
        sample for sample in meta["sample"].astype(str).tolist() if sample in frame.columns
    ]
    meta = meta[meta["sample"].astype(str).isin(sample_columns)].copy()

    if "condition" not in meta.columns:
        meta["condition"] = meta["sample"]

    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    if not sample_columns:
        raise ValueError(f"No sample columns available for {kind} dataset.")
    return frame, meta, sample_columns


def _id_column(kind: AnnotationKind, frame: pd.DataFrame) -> str:
    if kind == "protein":
        candidates = ["ProteinNames", "Protein", "Gene"]
    else:
        candidates = ["PTM_Collapse_key", "Phosphoprotein", "Protein_group"]
    for col in candidates:
        if col in frame.columns:
            return col
    raise ValueError(f"No identifier column found for {kind} dataset.")


def comparison_options(
    kind: AnnotationKind,
) -> dict[str, list[str] | int | bool | str]:
    source_used = "data"
    frame, meta = qc_matrix(kind)
    sample_columns = [
        sample for sample in meta["sample"].astype(str).tolist()
        if sample in frame.columns
    ]
    meta = meta[meta["sample"].astype(str).isin(sample_columns)].copy()
    samples = (
        meta["sample"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .drop_duplicates()
        .tolist()
    )
    conditions = (
        meta["condition"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .drop_duplicates()
        .tolist()
    )
    return {
        "samples": samples,
        "conditions": conditions,
        "sampleCount": len(samples),
        "conditionCount": len(conditions),
        "dataSource": source_used,
    }


def _pearson_vectors(
    kind: AnnotationKind,
    mode: str,
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    min_present: int = 1,
) -> tuple[pd.Series, pd.Series, str, str]:
    frame, meta, _ = _analysis_context(kind)
    mode_norm = str(mode).strip().lower()

    if mode_norm in {"single", "sample"}:
        if not sample1 or not sample2:
            raise ValueError("Please select two samples.")
        if sample1 == sample2:
            raise ValueError("Please select two different samples.")
        if sample1 not in frame.columns or sample2 not in frame.columns:
            raise ValueError("Selected samples are not available in the current dataset.")

        x = pd.to_numeric(frame[sample1], errors="coerce")
        y = pd.to_numeric(frame[sample2], errors="coerce")
        return x, y, sample1, sample2

    if mode_norm == "condition":
        if not condition1 or not condition2:
            raise ValueError("Please select two conditions.")
        if condition1 == condition2:
            raise ValueError("Please select two different conditions.")

        cols1 = meta.loc[meta["condition"] == condition1, "sample"].astype(str).tolist()
        cols2 = meta.loc[meta["condition"] == condition2, "sample"].astype(str).tolist()
        cols1 = [col for col in cols1 if col in frame.columns]
        cols2 = [col for col in cols2 if col in frame.columns]
        if not cols1 or not cols2:
            raise ValueError("No matching sample columns for one or both selected conditions.")

        x, _ = condition_mean(frame, cols1, min_present=min_present)
        y, _ = condition_mean(frame, cols2, min_present=min_present)
        return x, y, condition1, condition2

    raise ValueError("Mode must be 'Single' or 'Condition'.")


def _pearson_vectors_with_features(
    kind: AnnotationKind,
    mode: str,
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    min_present: int = 1,
) -> tuple[pd.Series, pd.Series, pd.Series, str, str]:
    frame, meta, _ = _analysis_context(kind)
    mode_norm = str(mode).strip().lower()
    id_col = _id_column(kind, frame)
    features = frame[id_col].fillna("").astype(str)

    if mode_norm in {"single", "sample"}:
        if not sample1 or not sample2:
            raise ValueError("Please select two samples.")
        if sample1 == sample2:
            raise ValueError("Please select two different samples.")
        if sample1 not in frame.columns or sample2 not in frame.columns:
            raise ValueError("Selected samples are not available in the current dataset.")

        x = pd.to_numeric(frame[sample1], errors="coerce")
        y = pd.to_numeric(frame[sample2], errors="coerce")
        return x, y, features, sample1, sample2

    if mode_norm == "condition":
        if not condition1 or not condition2:
            raise ValueError("Please select two conditions.")
        if condition1 == condition2:
            raise ValueError("Please select two different conditions.")

        cols1 = meta.loc[meta["condition"] == condition1, "sample"].astype(str).tolist()
        cols2 = meta.loc[meta["condition"] == condition2, "sample"].astype(str).tolist()
        cols1 = [col for col in cols1 if col in frame.columns]
        cols2 = [col for col in cols2 if col in frame.columns]
        if not cols1 or not cols2:
            raise ValueError("No matching sample columns for one or both selected conditions.")

        x, _ = condition_mean(frame, cols1, min_present=min_present)
        y, _ = condition_mean(frame, cols2, min_present=min_present)
        return x, y, features, condition1, condition2

    raise ValueError("Mode must be 'Single' or 'Condition'.")


def pearson_correlation_table(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    min_present: int = 1,
) -> pd.DataFrame:
    x, y, label1, label2 = _pearson_vectors(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
        min_present=min_present,
    )

    pairs = pd.DataFrame({"x": x, "y": y}).dropna()
    if pairs.empty:
        raise ValueError("No overlapping non-missing values were found for the selected comparison.")

    label_left = alias1.strip() or label1
    label_right = alias2.strip() or label2
    corr = float(np.corrcoef(pairs["x"], pairs["y"])[0, 1]) if len(pairs) > 1 else float("nan")

    return pd.DataFrame(
        [
            {"Metric": "Left", "Value": label_left},
            {"Metric": "Right", "Value": label_right},
            {"Metric": "Points", "Value": int(len(pairs))},
            {"Metric": "PearsonR", "Value": round(corr, 6) if np.isfinite(corr) else ""},
        ]
    )


def pearson_correlation_png(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 60,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    plt = _get_plt()
    x, y, label1, label2 = _pearson_vectors(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
    )
    pairs = pd.DataFrame({"x": x, "y": y}).dropna()
    if pairs.empty:
        raise ValueError("No overlapping non-missing values were found for the selected comparison.")

    left = alias1.strip() or _rename_if_condition(label1, mode, advanced)
    right = alias2.strip() or _rename_if_condition(label2, mode, advanced)
    corr = float(np.corrcoef(pairs["x"], pairs["y"])[0, 1]) if len(pairs) > 1 else float("nan")

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    ax.scatter(
        pairs["x"].to_numpy(dtype=float),
        pairs["y"].to_numpy(dtype=float),
        # `dot_size` is the legacy control, kept for the notebook API. The
        # advanced setting is a diameter, like every other plot's; the old one
        # was a matplotlib area here and the square root of that in the plotly
        # twin, so one number drew two different dots.
        **marker_style(
            advanced,
            size=_legacy_area_as_diameter(dot_size),
            alpha=0.65,
            color_default=color,
        ),
    )
    # The same least-squares line the interactive twin, the pip package and the
    # R script draw, under the same reference-line setting, so the report's
    # figure is the figure on screen.
    fit_line = resolve_reference_line(advanced, color="#475569", style="solid", width=2.0)
    if len(pairs) > 1 and fit_line.visible:
        slope, intercept = np.polyfit(pairs["x"].to_numpy(dtype=float), pairs["y"].to_numpy(dtype=float), 1)
        line_x = np.array([float(pairs["x"].min()), float(pairs["x"].max())], dtype=float)
        ax.plot(line_x, slope * line_x + intercept, zorder=3, **fit_line.matplotlib())
    ax.set_xlabel(_wrap_label(left, width_cm))
    ax.set_ylabel(_wrap_label(right, height_cm))
    if header:
        ax.set_title(_wrap_label(f"Pearson Correlation: {left} vs {right}", width_cm))
    note = f"r = {corr:.4f}\nN = {len(pairs)}" if np.isfinite(corr) else f"r = n/a\nN = {len(pairs)}"
    ax.text(
        0.02,
        0.98,
        note,
        transform=ax.transAxes,
        ha="left",
        va="top",
        bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"},
    )
    ax.grid(True, alpha=0.2)
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


def pearson_correlation_html(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dot_size: float = 8,
    header: bool = True,
    width_cm: float = 20,
    height_cm: float = 12,
    advanced: dict | None = None,
) -> str:
    go = _get_plotly()
    x, y, features, label1, label2 = _pearson_vectors_with_features(
        kind=kind,
        mode=mode,
        sample1=sample1,
        sample2=sample2,
        condition1=condition1,
        condition2=condition2,
    )
    points = pd.DataFrame(
        {
            "feature": features.astype(str),
            "x": pd.to_numeric(x, errors="coerce"),
            "y": pd.to_numeric(y, errors="coerce"),
        }
    ).dropna(subset=["x", "y"])
    if points.empty:
        raise ValueError("No overlapping non-missing values were found for the selected comparison.")

    points["feature"] = points["feature"].replace("", "n/a")
    points["feature_short"] = points["feature"].map(lambda value: _truncate_hover_text(value, max_len=48))
    points["diff"] = points["y"] - points["x"]

    left = alias1.strip() or _rename_if_condition(label1, mode, advanced)
    right = alias2.strip() or _rename_if_condition(label2, mode, advanced)
    left_short = _truncate_hover_text(left, max_len=16)
    right_short = _truncate_hover_text(right, max_len=16)
    corr = float(np.corrcoef(points["x"], points["y"])[0, 1]) if len(points) > 1 else float("nan")

    custom_data = np.column_stack(
        [
            points["feature"].to_numpy(dtype=object),
            points["diff"].to_numpy(dtype=float),
            points["feature_short"].to_numpy(dtype=object),
        ]
    )
    hover_template = (
        "Feature: %{customdata[2]}<br>"
        f"{left_short}: %{{x:.4f}}<br>"
        f"{right_short}: %{{y:.4f}}<br>"
        f"Diff ({right_short} - {left_short}): %{{customdata[1]:.4f}}"
        "<extra></extra>"
    )

    marker = plotly_marker(
        advanced,
        size=_legacy_area_as_diameter(dot_size),
        alpha=0.65,
        color_default=color,
    )

    fig = go.Figure()
    fig.add_trace(
        # SVG, not Scattergl: see plot_webgl - WebGL fails outright without
        # hardware acceleration, and _plotly_html enforces the same policy.
        go.Scatter(
            x=points["x"],
            y=points["y"],
            mode="markers",
            marker=marker,
            customdata=custom_data,
            hovertemplate=hover_template,
            showlegend=False,
            name="Points",
        )
    )

    fit_line = resolve_reference_line(advanced, color="#475569", style="solid", width=2.0)
    if len(points) > 1 and fit_line.visible:
        slope, intercept = np.polyfit(points["x"], points["y"], 1)
        x_min = float(points["x"].min())
        x_max = float(points["x"].max())
        line_x = np.array([x_min, x_max], dtype=float)
        line_y = slope * line_x + intercept
        fig.add_trace(
            go.Scatter(
                x=line_x,
                y=line_y,
                mode="lines",
                line=fit_line.plotly(),
                hoverinfo="skip",
                showlegend=False,
                name="Fit",
            )
        )

    fig.update_layout(
        title=(f"Pearson Correlation: {left} vs {right}" if header else None),
        xaxis_title=left,
        yaxis_title=right,
        template="plotly_white",
        autosize=True,
        height=_cm_to_px(height_cm),
        margin=dict(l=50, r=24, t=(70 if header else 20), b=50),
    )
    fig.update_layout(
        **advanced_plotly_layout(
            advanced,
            width_px=_cm_to_px(width_cm),
            height_px=_cm_to_px(height_cm),
        )
    )
    note = f"r = {corr:.4f}<br>N = {len(points)}" if np.isfinite(corr) else f"r = n/a<br>N = {len(points)}"
    fig.add_annotation(
        x=0.01,
        y=0.99,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="left",
        text=note,
        bgcolor="rgba(255,255,255,0.85)",
    )
    return _plotly_html(fig)


def _feature_set_from_sample(frame: pd.DataFrame, id_col: str, sample: str) -> set[str]:
    if sample not in frame.columns:
        raise ValueError(f"Sample '{sample}' is not available.")
    mask = pd.to_numeric(frame[sample], errors="coerce").notna()
    return set(frame.loc[mask, id_col].dropna().astype(str).tolist())


def _feature_set_from_condition(frame: pd.DataFrame, meta: pd.DataFrame, id_col: str, condition: str) -> set[str]:
    columns = meta.loc[meta["condition"] == condition, "sample"].astype(str).tolist()
    columns = [col for col in columns if col in frame.columns]
    if not columns:
        raise ValueError(f"Condition '{condition}' has no available sample columns.")
    values = frame[columns].apply(pd.to_numeric, errors="coerce")
    mask = values.notna().any(axis=1)
    return set(frame.loc[mask, id_col].dropna().astype(str).tolist())


def _venn_sets(
    kind: AnnotationKind,
    mode: str,
    first: str,
    second: str,
    third: str = "",
) -> tuple[set[str], set[str], set[str] | None]:
    frame, meta, _ = _analysis_context(kind)
    id_col = _id_column(kind, frame)
    mode_norm = str(mode).strip().lower()
    if not first or not second:
        raise ValueError("Please select at least two entries for the Venn diagram.")
    if first == second:
        raise ValueError("Please select two different entries.")
    if third and (third == first or third == second):
        raise ValueError("Please select distinct entries for the third set.")

    if mode_norm in {"single", "sample"}:
        set1 = _feature_set_from_sample(frame, id_col, first)
        set2 = _feature_set_from_sample(frame, id_col, second)
        set3 = _feature_set_from_sample(frame, id_col, third) if third else None
        return set1, set2, set3
    if mode_norm == "condition":
        set1 = _feature_set_from_condition(frame, meta, id_col, first)
        set2 = _feature_set_from_condition(frame, meta, id_col, second)
        set3 = _feature_set_from_condition(frame, meta, id_col, third) if third else None
        return set1, set2, set3
    raise ValueError("Mode must be 'Single' or 'Condition'.")


def venn_table(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
) -> pd.DataFrame:
    set1, set2, set3 = _venn_sets(
        kind=kind,
        mode=mode,
        first=first,
        second=second,
        third=third,
    )
    label1 = alias1.strip() or first
    label2 = alias2.strip() or second
    label3 = alias3.strip() or third

    if set3 is None:
        return pd.DataFrame(
            [
                {"Region": f"{label1} only", "Count": len(set1 - set2)},
                {"Region": f"{label2} only", "Count": len(set2 - set1)},
                {"Region": f"{label1} & {label2}", "Count": len(set1 & set2)},
                {"Region": f"Total {label1}", "Count": len(set1)},
                {"Region": f"Total {label2}", "Count": len(set2)},
            ]
        )

    return pd.DataFrame(
        [
            {"Region": f"{label1} only", "Count": len(set1 - set2 - set3)},
            {"Region": f"{label2} only", "Count": len(set2 - set1 - set3)},
            {"Region": f"{label3} only", "Count": len(set3 - set1 - set2)},
            {"Region": f"{label1} & {label2}", "Count": len((set1 & set2) - set3)},
            {"Region": f"{label1} & {label3}", "Count": len((set1 & set3) - set2)},
            {"Region": f"{label2} & {label3}", "Count": len((set2 & set3) - set1)},
            {"Region": f"{label1} & {label2} & {label3}", "Count": len(set1 & set2 & set3)},
            {"Region": f"Total {label1}", "Count": len(set1)},
            {"Region": f"Total {label2}", "Count": len(set2)},
            {"Region": f"Total {label3}", "Count": len(set3)},
        ]
    )


def venn_png(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
    color1: str = "#1f77b4",
    color2: str = "#ff7f0e",
    color3: str = "#2ca02c",
    header: bool = True,
    width_cm: float = 15,
    height_cm: float = 12,
    dpi: int = 300,
    advanced: dict | None = None,
) -> bytes:
    plt = _get_plt()
    venn2, venn3 = _get_venn()
    set1, set2, set3 = _venn_sets(
        kind=kind,
        mode=mode,
        first=first,
        second=second,
        third=third,
    )
    label1 = alias1.strip() or _rename_if_condition(first, mode, advanced)
    label2 = alias2.strip() or _rename_if_condition(second, mode, advanced)
    label3 = alias3.strip() or _rename_if_condition(third, mode, advanced)

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    if set3 is None:
        venn2(
            [set1, set2],
            set_labels=tuple(_wrap_label(label, width_cm / 2) for label in (label1, label2)),
            set_colors=(
                advanced_color(advanced, "vennColor1", color1),
                advanced_color(advanced, "vennColor2", color2),
            ),
            alpha=0.5,
            ax=ax,
        )
    else:
        venn3(
            [set1, set2, set3],
            set_labels=tuple(_wrap_label(label, width_cm / 2) for label in (label1, label2, label3)),
            set_colors=(
                advanced_color(advanced, "vennColor1", color1),
                advanced_color(advanced, "vennColor2", color2),
                advanced_color(advanced, "vennColor3", color3),
            ),
            alpha=0.5,
            ax=ax,
        )
    if header:
        mode_label = "samples" if str(mode).strip().lower() in {"single", "sample"} else "conditions"
        ax.set_title(f"Venn Diagram ({mode_label})")
    apply_advanced_axes(ax, advanced)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi, tight=False)


apply_cached_wrappers(
    globals(),
    [
        "comparison_options",
        "pearson_correlation_table",
        "pearson_correlation_png",
        "pearson_correlation_html",
        "venn_table",
        "venn_png",
    ],
)

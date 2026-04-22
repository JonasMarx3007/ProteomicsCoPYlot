from __future__ import annotations

import io

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame, _get_sample_columns
from app.services.runtime_cache import apply_cached_wrappers


def _get_plt():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib is required for comparison plot rendering. Install it with: pip install matplotlib"
        ) from exc


def _get_venn():
    try:
        from matplotlib_venn import venn2, venn3

        return venn2, venn3
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "matplotlib-venn is required for Venn diagrams. Install it with: pip install matplotlib-venn"
        ) from exc


def _get_plotly():
    try:
        import plotly.graph_objects as go

        return go
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "plotly is required for interactive comparison plots. Install it with: pip install plotly"
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
    return max(320, int(round((_cm_to_inch(value_cm) * 96.0))))


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
        ".js-plotly-plot,.plotly-graph-div,.plot-container,.svg-container{width:100%!important;height:100%!important;min-height:420px;}"
        "</style>"
        "</head><body>"
        "<div id='plot-root'>"
        f"{body}"
        "</div>"
        "<script>"
        "(function(){"
        "function firstPlot(){return document.querySelector('.js-plotly-plot,.plotly-graph-div');}"
        "function resolveLayoutHeight(el){"
        "if(!el){return 0;}"
        "var value=0;"
        "if(el.layout && Number.isFinite(Number(el.layout.height))){value=Number(el.layout.height);}"
        "else if(el._fullLayout && Number.isFinite(Number(el._fullLayout.height))){value=Number(el._fullLayout.height);}"
        "return Math.max(0,value);"
        "}"
        "function resizePlot(){"
        "var el=firstPlot();"
        "if(!(el && window.Plotly)){return;}"
        "var root=document.getElementById('plot-root');"
        "var rootWidth=(root && Number(root.clientWidth))||0;"
        "var rootHeight=(root && Number(root.clientHeight))||0;"
        "var viewportWidth=Math.max(360,rootWidth,(window.innerWidth||0)-8);"
        "var viewportHeight=Math.max(420,rootHeight,(window.innerHeight||0)-8);"
        "var layoutHeight=resolveLayoutHeight(el);"
        "var nextHeight=Math.max(layoutHeight,viewportHeight);"
        "window.Plotly.relayout(el,{width:viewportWidth,height:nextHeight,autosize:true}).catch(function(){});"
        "window.Plotly.Plots.resize(el);"
        "}"
        "window.addEventListener('load', resizePlot);"
        "window.addEventListener('resize', resizePlot);"
        "if(window.ResizeObserver){"
        "var rootEl=document.getElementById('plot-root');"
        "if(rootEl){(new ResizeObserver(function(){resizePlot();})).observe(rootEl);}"
        "}"
        "setTimeout(resizePlot, 80);"
        "setTimeout(resizePlot, 260);"
        "setTimeout(resizePlot, 800);"
        "setTimeout(resizePlot, 1500);"
        "})();"
        "</script>"
        "</body></html>"
    )


def _truncate_hover_text(value: object, max_len: int) -> str:
    text = str(value or "").strip()
    if not text:
        return "n/a"
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:1]
    return f"{text[: max_len - 1]}..."


def _analysis_context(kind: AnnotationKind) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is not None and not annotation.log2_data.empty:
        frame = annotation.log2_data.copy()
    elif annotation is not None and not annotation.filtered_data.empty:
        frame = annotation.filtered_data.copy()
    elif annotation is not None and not annotation.source_data.empty:
        frame = annotation.source_data.copy()
    else:
        frame = raw.copy()

    if annotation is not None and not annotation.metadata.empty:
        meta = annotation.metadata.copy()
        sample_columns = [sample for sample in meta["sample"].astype(str).tolist() if sample in frame.columns]
        meta = meta[meta["sample"].isin(sample_columns)].copy()
    else:
        sample_columns = _get_sample_columns(kind, frame)
        meta = pd.DataFrame({"sample": sample_columns, "condition": sample_columns})

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


def comparison_options(kind: AnnotationKind) -> dict[str, list[str] | int]:
    _, meta, _ = _analysis_context(kind)
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
    }


def _pearson_vectors(
    kind: AnnotationKind,
    mode: str,
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
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

        x = frame[cols1].apply(pd.to_numeric, errors="coerce").mean(axis=1)
        y = frame[cols2].apply(pd.to_numeric, errors="coerce").mean(axis=1)
        return x, y, condition1, condition2

    raise ValueError("Mode must be 'Single' or 'Condition'.")


def _pearson_vectors_with_features(
    kind: AnnotationKind,
    mode: str,
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
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

        x = frame[cols1].apply(pd.to_numeric, errors="coerce").mean(axis=1)
        y = frame[cols2].apply(pd.to_numeric, errors="coerce").mean(axis=1)
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
) -> pd.DataFrame:
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

    left = alias1.strip() or label1
    right = alias2.strip() or label2
    corr = float(np.corrcoef(pairs["x"], pairs["y"])[0, 1]) if len(pairs) > 1 else float("nan")

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    ax.scatter(
        pairs["x"].to_numpy(dtype=float),
        pairs["y"].to_numpy(dtype=float),
        c=color,
        s=max(1.0, float(dot_size)),
        alpha=0.65,
        edgecolors="none",
    )
    ax.set_xlabel(left)
    ax.set_ylabel(right)
    if header:
        ax.set_title(f"Pearson Correlation: {left} vs {right}")
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

    left = alias1.strip() or label1
    right = alias2.strip() or label2
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

    marker_size = max(2.0, float(np.sqrt(max(1.0, float(dot_size)))))

    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=points["x"],
            y=points["y"],
            mode="markers",
            marker=dict(
                size=marker_size,
                color=color,
                opacity=0.65,
                line=dict(width=0),
            ),
            customdata=custom_data,
            hovertemplate=hover_template,
            showlegend=False,
            name="Points",
        )
    )

    if len(points) > 1:
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
                line=dict(color="#475569", width=2),
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
    set1, set2, set3 = _venn_sets(kind=kind, mode=mode, first=first, second=second, third=third)
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
) -> bytes:
    plt = _get_plt()
    venn2, venn3 = _get_venn()
    set1, set2, set3 = _venn_sets(kind=kind, mode=mode, first=first, second=second, third=third)
    label1 = alias1.strip() or first
    label2 = alias2.strip() or second
    label3 = alias3.strip() or third

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)))
    if set3 is None:
        venn2(
            [set1, set2],
            set_labels=(label1, label2),
            set_colors=(color1, color2),
            alpha=0.5,
            ax=ax,
        )
    else:
        venn3(
            [set1, set2, set3],
            set_labels=(label1, label2, label3),
            set_colors=(color1, color2, color3),
            alpha=0.5,
            ax=ax,
        )
    if header:
        mode_label = "samples" if str(mode).strip().lower() in {"single", "sample"} else "conditions"
        ax.set_title(f"Venn Diagram ({mode_label})")
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

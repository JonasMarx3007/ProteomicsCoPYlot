from __future__ import annotations

import io
import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.condition_palette_store import build_condition_color_map
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
    if getattr(fig, "_copylot_transparent_background", False):
        save_kwargs["transparent"] = True
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


def _plotly_html_background(fig) -> str:
    try:
        value = str(fig.layout.paper_bgcolor or "#fff").strip()
    except Exception:
        return "#fff"
    return value if value else "#fff"


def _plotly_html(fig) -> str:
    bg = _plotly_html_background(fig)
    body = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "responsive": True},
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        f"html,body{{margin:0;padding:0;background:{bg};width:100%;height:100%;}}"
        "#plot-root{width:100%;height:100%;}"
        ".js-plotly-plot,.plotly-graph-div{width:100%!important;min-height:360px;}"
        "</style>"
        "</head><body>"
        "<div id='plot-root'>"
        f"{body}"
        "</div>"
        "<script>"
        "(function(){"
        "function firstPlot(){"
        "return document.querySelector('.js-plotly-plot,.plotly-graph-div');"
        "}"
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
        "var viewportHeight=Math.max(360,(window.innerHeight||0)-8);"
        "var layoutHeight=resolveLayoutHeight(el);"
        "var nextHeight=Math.max(layoutHeight,viewportHeight);"
        "window.Plotly.relayout(el,{height:nextHeight}).catch(function(){});"
        "window.Plotly.Plots.resize(el);"
        "}"
        "window.addEventListener('load', resizePlot);"
        "window.addEventListener('resize', resizePlot);"
        "setTimeout(resizePlot, 80);"
        "setTimeout(resizePlot, 260);"
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


def _original_scale_frame(kind: AnnotationKind):
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


def _peptide_file_column(frame: pd.DataFrame) -> str:
    if "File.Name" in frame.columns:
        return "File.Name"
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "file" in normalized and "name" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a file-name column.")


def _peptide_sequence_column(frame: pd.DataFrame) -> str:
    if "Stripped.Sequence" in frame.columns:
        return "Stripped.Sequence"
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "stripped" in normalized and "sequence" in normalized:
            return str(column)
    raise ValueError("Peptide dataset is missing a stripped-sequence column.")


def _peptide_quantity_column(frame: pd.DataFrame) -> str:
    if "Precursor.Quantity" in frame.columns:
        return "Precursor.Quantity"
    for column in frame.columns:
        normalized = str(column).strip().lower()
        if "quantity" in normalized:
            return str(column)
    numeric_cols = frame.select_dtypes(include=[np.number]).columns.astype(str).tolist()
    if numeric_cols:
        return numeric_cols[0]
    raise ValueError("Peptide dataset is missing a usable quantity column.")


def _peptide_coverage_metadata(frame: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    # Reuse the exact metadata preparation used by peptide modification/missed-cleavage
    # so peptide coverage follows the same shared proteome metadata behavior.
    from app.services.peptide_tools import _prepare_metadata as _prepare_peptide_metadata

    meta = _prepare_peptide_metadata(frame, include_id=include_id).copy()
    return meta.rename(columns={"new_sample": "label"})


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


def _extract_id_or_number(sample: str) -> str:
    match = re.search(r"\d+|[A-Za-z]+", str(sample))
    return match.group(0) if match else str(sample)


def _sample_label(sample: str, condition: str, index: int, include_id: bool) -> str:
    if not include_id:
        return f"{condition}_{index + 1}"
    sid = _extract_id_or_number(sample)
    return f"{condition}_{index + 1}\n({sid})"


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


def _condition_colors(kind: AnnotationKind, _plt, conditions: list[str]) -> dict[str, str]:
    return build_condition_color_map(kind, _normalized_conditions(conditions))


def parse_advanced_plot_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _advanced_text(settings: dict[str, Any] | None, key: str) -> str | None:
    value = (settings or {}).get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _advanced_number(settings: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    value = (settings or {}).get(key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _advanced_optional_number(settings: dict[str, Any] | None, key: str) -> float | None:
    if not settings or key not in settings:
        return None
    value = settings.get(key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _advanced_bool(settings: dict[str, Any] | None, key: str, default: bool = False) -> bool:
    if not settings or key not in settings:
        return default
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _advanced_choice(settings: dict[str, Any] | None, key: str, allowed: set[str], default: str) -> str:
    value = _advanced_text(settings, key)
    if value in allowed:
        return value
    return default


def _advanced_color_text(settings: dict[str, Any] | None, key: str) -> str | None:
    value = _advanced_text(settings, key)
    if not value:
        return None
    return value


_PLOT_THEME_MAP: dict[str, dict[str, str]] = {
    "white": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#111827",
        "axis": "#111827",
        "grid": "#e5e7eb",
        "plotly_template": "plotly_white",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "minimal": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#111827",
        "axis": "#111827",
        "grid": "#f1f5f9",
        "plotly_template": "simple_white",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "soft_gray": {
        "mpl_figure": "#f8fafc",
        "mpl_axes": "#ffffff",
        "text": "#0f172a",
        "axis": "#334155",
        "grid": "#cbd5e1",
        "plotly_template": "plotly_white",
        "plotly_paper": "#f8fafc",
        "plotly_plot": "#ffffff",
    },
    "presentation": {
        "mpl_figure": "#ffffff",
        "mpl_axes": "#ffffff",
        "text": "#020617",
        "axis": "#020617",
        "grid": "#d1d5db",
        "plotly_template": "presentation",
        "plotly_paper": "#ffffff",
        "plotly_plot": "#ffffff",
    },
    "dark": {
        "mpl_figure": "#111827",
        "mpl_axes": "#0f172a",
        "text": "#e5e7eb",
        "axis": "#cbd5e1",
        "grid": "#334155",
        "plotly_template": "plotly_dark",
        "plotly_paper": "#111827",
        "plotly_plot": "#0f172a",
    },
}


def _advanced_theme(settings: dict[str, Any] | None) -> dict[str, str]:
    theme_id = _advanced_choice(settings, "plotTheme", set(_PLOT_THEME_MAP), "default")
    return _PLOT_THEME_MAP.get(theme_id, {})


def _mpl_axis_line_style(settings: dict[str, Any] | None) -> str:
    style = _advanced_choice(settings, "axisLineStyle", {"solid", "dashed", "dotted", "dashdot"}, "solid")
    return {
        "solid": "-",
        "dashed": "--",
        "dotted": ":",
        "dashdot": "-.",
    }.get(style, "-")


def _mpl_grid_line_style(settings: dict[str, Any] | None) -> str:
    style = _advanced_choice(settings, "gridLineStyle", {"solid", "dashed", "dotted", "dashdot"}, "solid")
    return {
        "solid": "-",
        "dashed": "--",
        "dotted": ":",
        "dashdot": "-.",
    }.get(style, "-")


def _plotly_grid_line_style(settings: dict[str, Any] | None) -> str:
    style = _advanced_choice(settings, "gridLineStyle", {"solid", "dashed", "dotted", "dashdot"}, "solid")
    return {
        "solid": "solid",
        "dashed": "dash",
        "dotted": "dot",
        "dashdot": "dashdot",
    }.get(style, "solid")


def _advanced_axis_sides(settings: dict[str, Any] | None) -> dict[str, bool]:
    return {
        "left": _advanced_bool(settings, "axisLineLeft", True),
        "right": _advanced_bool(settings, "axisLineRight", True),
        "bottom": _advanced_bool(settings, "axisLineBottom", True),
        "top": _advanced_bool(settings, "axisLineTop", True),
    }


def _advanced_map(settings: dict[str, Any] | None, key: str) -> dict[str, str]:
    value = (settings or {}).get(key)
    if not isinstance(value, dict):
        return {}
    output: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        map_key = str(raw_key).strip()
        map_value = str(raw_value).strip()
        if map_key and map_value:
            output[map_key] = map_value
    return output


def _advanced_lookup_key(value: str) -> str:
    text = str(value).replace("\n", " ").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _advanced_map_lookup(mapping: dict[str, str], *values: object) -> str | None:
    normalized = {_advanced_lookup_key(key): val for key, val in mapping.items()}
    for value in values:
        if value is None:
            continue
        text = str(value)
        candidates = [
            text,
            text.replace("\n", " "),
            text.replace("_", " "),
            text.replace(" ", "_"),
        ]
        for candidate in candidates:
            if candidate in mapping:
                return mapping[candidate]
            match = normalized.get(_advanced_lookup_key(candidate))
            if match is not None:
                return match
    return None


def _advanced_element(settings: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = (settings or {}).get(key)
    return value if isinstance(value, dict) else {}


def _advanced_element_text(
    settings: dict[str, Any] | None,
    element_key: str,
    legacy_key: str,
) -> str | None:
    element = _advanced_element(settings, element_key)
    text = element.get("text")
    if text is not None:
        clean = str(text).strip()
        if clean:
            return clean
    return _advanced_text(settings, legacy_key)


def _advanced_element_number(
    settings: dict[str, Any] | None,
    element_key: str,
    element_number_key: str,
    legacy_key: str | None = None,
) -> float:
    element = _advanced_element(settings, element_key)
    value = element.get(element_number_key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _advanced_number(settings, legacy_key, 0.0) if legacy_key else 0.0
    return number if math.isfinite(number) else 0.0


def _advanced_element_font_props(
    settings: dict[str, Any] | None,
    element_key: str,
) -> dict[str, Any]:
    element = _advanced_element(settings, element_key)
    props: dict[str, Any] = {}
    if element.get("bold"):
        props["fontweight"] = "bold"
    if element.get("italic"):
        props["fontstyle"] = "italic"
    return props


def _advanced_label(value: str, settings: dict[str, Any] | None, key: str, *aliases: object) -> str:
    labels = _advanced_map(settings, key)
    value_text = str(value)
    return _advanced_map_lookup(labels, value_text, *aliases) or value_text


def _advanced_color(value: str, default: str, settings: dict[str, Any] | None) -> str:
    colors = _advanced_map(settings, "conditionColors")
    value_text = str(value)
    display_text = _advanced_label(value_text, settings, "conditionLabels")
    return _advanced_map_lookup(colors, value_text, display_text) or default


def _advanced_condition_colors(
    kind: AnnotationKind,
    plt,
    conditions: list[str],
    settings: dict[str, Any] | None,
) -> dict[str, str]:
    base = _condition_colors(kind, plt, conditions)
    return {condition: _advanced_color(condition, color, settings) for condition, color in base.items()}


def _fig_pixel_fraction(fig, pixels: float, axis: str) -> float:
    try:
        width_in, height_in = fig.get_size_inches()
        dpi = float(fig.dpi)
    except Exception:
        width_in, height_in, dpi = 10.0, 6.0, 100.0
    denominator = width_in * dpi if axis == "x" else height_in * dpi
    return pixels / denominator if denominator else 0.0


def _plotly_pixel_fraction(pixels: float, total_px: int) -> float:
    return pixels / max(1, int(total_px))


def _advanced_anchor(ax, settings: dict[str, Any] | None, x: float, y: float) -> tuple[float, float]:
    return (
        x + _fig_pixel_fraction(ax.figure, _advanced_number(settings, "legendXOffset", 0.0), "x"),
        y + _fig_pixel_fraction(ax.figure, _advanced_number(settings, "legendYOffset", 0.0), "y"),
    )


def _advanced_text_position(settings: dict[str, Any] | None, x: float, y: float) -> tuple[float, float]:
    return (
        x + _advanced_number(settings, "textXOffset", 0.0),
        y + _advanced_number(settings, "textYOffset", 0.0),
    )


def _style_legend(legend, settings: dict[str, Any] | None) -> None:
    if legend is None:
        return
    size = _advanced_number(settings, "legendFontSize", 0.0)
    for text in legend.get_texts():
        if size > 0:
            text.set_fontsize(size)
    title = legend.get_title()
    if title is not None:
        if size > 0:
            title.set_fontsize(size)


def _apply_advanced_matplotlib_style(ax, settings: dict[str, Any] | None) -> None:
    if not settings:
        return
    fig = ax.figure
    theme = _advanced_theme(settings)
    text_color = theme.get("text")
    axis_color = theme.get("axis")
    grid_color = theme.get("grid")
    background = _advanced_color_text(settings, "backgroundColor")
    transparent = _advanced_bool(settings, "transparentBackground", False)

    if theme:
        fig.patch.set_facecolor(theme.get("mpl_figure", "#ffffff"))
        ax.set_facecolor(theme.get("mpl_axes", "#ffffff"))
    if background:
        fig.patch.set_facecolor(background)
        ax.set_facecolor(background)
    if transparent:
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)
        setattr(fig, "_copylot_transparent_background", True)
    else:
        setattr(fig, "_copylot_transparent_background", False)

    if text_color:
        ax.title.set_color(text_color)
        ax.xaxis.label.set_color(text_color)
        ax.yaxis.label.set_color(text_color)
        for label in [*ax.get_xticklabels(), *ax.get_yticklabels()]:
            label.set_color(text_color)
        legend = ax.get_legend()
        if legend is not None:
            for text in legend.get_texts():
                text.set_color(text_color)
            legend.get_title().set_color(text_color)

    if grid_color:
        for line in [*ax.get_xgridlines(), *ax.get_ygridlines()]:
            line.set_color(grid_color)

    has_grid_line_setting = any(
        key in settings
        for key in ("gridLineVisible", "gridLineAxis", "gridLineColor", "gridLineWidth", "gridLineStyle")
    )
    if has_grid_line_setting:
        visible = _advanced_bool(settings, "gridLineVisible", True)
        if not visible:
            ax.grid(False)
        else:
            grid_axis = _advanced_choice(settings, "gridLineAxis", {"x", "y", "both"}, "y")
            grid_color_setting = _advanced_color_text(settings, "gridLineColor") or grid_color or "#d1d5db"
            grid_width = max(0.0, _advanced_number(settings, "gridLineWidth", 0.8))
            grid_style = _mpl_grid_line_style(settings)
            ax.grid(False)
            ax.grid(True, axis=grid_axis, color=grid_color_setting, linewidth=grid_width, linestyle=grid_style)

    has_axis_line_setting = any(
        key in settings
        for key in (
            "axisLineVisible",
            "axisLineColor",
            "axisLineWidth",
            "axisLineStyle",
            "axisLineTop",
            "axisLineRight",
            "axisLineBottom",
            "axisLineLeft",
        )
    )
    if axis_color or has_axis_line_setting:
        visible = _advanced_bool(settings, "axisLineVisible", True)
        line_color = _advanced_color_text(settings, "axisLineColor") or axis_color or "#111827"
        line_width = max(0.0, _advanced_number(settings, "axisLineWidth", 1.0))
        line_style = _mpl_axis_line_style(settings)
        side_keys_present = any(
            key in settings
            for key in ("axisLineTop", "axisLineRight", "axisLineBottom", "axisLineLeft")
        )
        sides = _advanced_axis_sides(settings)
        for name, spine in ax.spines.items():
            if not visible:
                spine.set_visible(False)
                continue
            if side_keys_present:
                spine.set_visible(sides.get(name, False))
            elif name in {"left", "bottom"} or spine.get_visible():
                spine.set_visible(True)
            if spine.get_visible():
                spine.set_color(line_color)
                spine.set_linewidth(line_width)
                spine.set_linestyle(line_style)
        if visible:
            ax.tick_params(axis="both", color=line_color)
        else:
            ax.tick_params(axis="both", length=0)


def _apply_advanced_axes(ax, settings: dict[str, Any] | None) -> None:
    if not settings:
        return
    _apply_advanced_matplotlib_style(ax, settings)
    title = _advanced_element_text(settings, "titleElement", "title")
    x_label = _advanced_element_text(settings, "xLabelElement", "xLabel")
    y_label = _advanced_element_text(settings, "yLabelElement", "yLabel")
    title_size = _advanced_element_number(settings, "titleElement", "size", "titleSize")
    x_axis_size = _advanced_element_number(settings, "xLabelElement", "size", "axisLabelSize")
    y_axis_size = _advanced_element_number(settings, "yLabelElement", "size", "axisLabelSize")
    legacy_tick_size = _advanced_number(settings, "tickLabelSize", 0.0)
    x_tick_size = _advanced_number(settings, "xTickLabelSize", legacy_tick_size)
    y_tick_size = _advanced_number(settings, "yTickLabelSize", legacy_tick_size)
    x_tick_rotation = _advanced_optional_number(settings, "xTickLabelRotation")
    y_tick_rotation = _advanced_optional_number(settings, "yTickLabelRotation")
    title_props = _advanced_element_font_props(settings, "titleElement")
    x_props = _advanced_element_font_props(settings, "xLabelElement")
    y_props = _advanced_element_font_props(settings, "yLabelElement")

    if title is not None:
        ax.set_title(title)
    if x_label is not None:
        ax.set_xlabel(x_label)
    if y_label is not None:
        ax.set_ylabel(y_label)

    title_obj = ax.title
    if title_size > 0:
        title_obj.set_fontsize(title_size)
    if "fontweight" in title_props:
        title_obj.set_fontweight(title_props["fontweight"])
    if "fontstyle" in title_props:
        title_obj.set_fontstyle(title_props["fontstyle"])
    if "fontweight" in x_props:
        ax.xaxis.label.set_fontweight(x_props["fontweight"])
    if "fontstyle" in x_props:
        ax.xaxis.label.set_fontstyle(x_props["fontstyle"])
    if "fontweight" in y_props:
        ax.yaxis.label.set_fontweight(y_props["fontweight"])
    if "fontstyle" in y_props:
        ax.yaxis.label.set_fontstyle(y_props["fontstyle"])
    if x_axis_size > 0:
        ax.xaxis.label.set_fontsize(x_axis_size)
    if y_axis_size > 0:
        ax.yaxis.label.set_fontsize(y_axis_size)
    title_x = _advanced_element_number(settings, "titleElement", "xOffset")
    title_y = _advanced_element_number(settings, "titleElement", "yOffset")
    if title_x or title_y:
        x_pos, y_pos = title_obj.get_position()
        title_obj.set_position(
            (
                x_pos + _fig_pixel_fraction(ax.figure, title_x, "x"),
                y_pos + _fig_pixel_fraction(ax.figure, title_y, "y"),
            )
        )
    x_label_x = _advanced_element_number(settings, "xLabelElement", "xOffset")
    x_label_y = _advanced_element_number(settings, "xLabelElement", "yOffset")
    if x_label_x or x_label_y:
        x_pos, y_pos = ax.xaxis.label.get_position()
        ax.xaxis.set_label_coords(
            x_pos + _fig_pixel_fraction(ax.figure, x_label_x, "x"),
            y_pos + _fig_pixel_fraction(ax.figure, x_label_y, "y"),
        )
    y_label_x = _advanced_element_number(settings, "yLabelElement", "xOffset")
    y_label_y = _advanced_element_number(settings, "yLabelElement", "yOffset")
    if y_label_x or y_label_y:
        x_pos, y_pos = ax.yaxis.label.get_position()
        ax.yaxis.set_label_coords(
            x_pos + _fig_pixel_fraction(ax.figure, y_label_x, "x"),
            y_pos + _fig_pixel_fraction(ax.figure, y_label_y, "y"),
        )
    if x_tick_size > 0:
        ax.tick_params(axis="x", labelsize=x_tick_size)
    if y_tick_size > 0:
        ax.tick_params(axis="y", labelsize=y_tick_size)
    if x_tick_rotation is not None:
        for label in ax.get_xticklabels():
            label.set_rotation(x_tick_rotation)
    if y_tick_rotation is not None:
        for label in ax.get_yticklabels():
            label.set_rotation(y_tick_rotation)
    _style_legend(ax.get_legend(), settings)


def _advanced_plotly_layout(
    settings: dict[str, Any] | None,
    width_px: int = 960,
    height_px: int = 540,
) -> dict[str, Any]:
    if not settings:
        return {}
    layout: dict[str, Any] = {}
    theme = _advanced_theme(settings)
    background = _advanced_color_text(settings, "backgroundColor")
    transparent = _advanced_bool(settings, "transparentBackground", False)
    title = _advanced_element_text(settings, "titleElement", "title")
    x_label = _advanced_element_text(settings, "xLabelElement", "xLabel")
    y_label = _advanced_element_text(settings, "yLabelElement", "yLabel")
    title_size = _advanced_element_number(settings, "titleElement", "size", "titleSize")
    x_axis_size = _advanced_element_number(settings, "xLabelElement", "size", "axisLabelSize")
    y_axis_size = _advanced_element_number(settings, "yLabelElement", "size", "axisLabelSize")
    legacy_tick_size = _advanced_number(settings, "tickLabelSize", 0.0)
    x_tick_size = _advanced_number(settings, "xTickLabelSize", legacy_tick_size)
    y_tick_size = _advanced_number(settings, "yTickLabelSize", legacy_tick_size)
    x_tick_rotation = _advanced_optional_number(settings, "xTickLabelRotation")
    y_tick_rotation = _advanced_optional_number(settings, "yTickLabelRotation")
    legend_size = _advanced_number(settings, "legendFontSize", 0.0)
    font: dict[str, Any] = {}
    if theme:
        layout["template"] = theme.get("plotly_template", "plotly_white")
        layout["paper_bgcolor"] = theme.get("plotly_paper", "#ffffff")
        layout["plot_bgcolor"] = theme.get("plotly_plot", "#ffffff")
        if theme.get("text"):
            font["color"] = theme["text"]
    if background:
        layout["paper_bgcolor"] = background
        layout["plot_bgcolor"] = background
    if transparent:
        layout["paper_bgcolor"] = "rgba(0,0,0,0)"
        layout["plot_bgcolor"] = "rgba(0,0,0,0)"
    if title is not None:
        layout["title"] = title
    if x_label is not None:
        layout["xaxis_title"] = x_label
    if y_label is not None:
        layout["yaxis_title"] = y_label
    if title_size > 0:
        layout.setdefault("title_font", {})["size"] = title_size
    title_x = _advanced_element_number(settings, "titleElement", "xOffset")
    title_y = _advanced_element_number(settings, "titleElement", "yOffset")
    if title_x or title_y:
        layout["title_x"] = 0.5 + _plotly_pixel_fraction(title_x, width_px)
        layout["title_y"] = 1.0 + _plotly_pixel_fraction(title_y, height_px)
    if x_axis_size > 0:
        layout.setdefault("xaxis", {}).setdefault("title", {})["font"] = {"size": x_axis_size}
    if y_axis_size > 0:
        layout.setdefault("yaxis", {}).setdefault("title", {})["font"] = {"size": y_axis_size}
    if x_tick_size > 0:
        layout.setdefault("xaxis", {})["tickfont"] = {"size": x_tick_size}
    if y_tick_size > 0:
        layout.setdefault("yaxis", {})["tickfont"] = {"size": y_tick_size}
    if x_tick_rotation is not None:
        layout.setdefault("xaxis", {})["tickangle"] = x_tick_rotation
    if y_tick_rotation is not None:
        layout.setdefault("yaxis", {})["tickangle"] = y_tick_rotation
    if theme:
        axis_color = theme.get("axis")
        grid_color = theme.get("grid")
        for axis_key in ("xaxis", "yaxis"):
            axis = layout.setdefault(axis_key, {})
            if axis_color:
                axis["linecolor"] = axis_color
                axis["tickcolor"] = axis_color
                axis.setdefault("tickfont", {})["color"] = theme.get("text", axis_color)
                axis.setdefault("title", {}).setdefault("font", {})["color"] = theme.get("text", axis_color)
                axis["zerolinecolor"] = axis_color
            if grid_color:
                axis["gridcolor"] = grid_color
    if any(key in settings for key in ("gridLineVisible", "gridLineAxis", "gridLineColor", "gridLineWidth", "gridLineStyle")):
        visible = _advanced_bool(settings, "gridLineVisible", True)
        grid_axis = _advanced_choice(settings, "gridLineAxis", {"x", "y", "both"}, "y")
        grid_color_setting = _advanced_color_text(settings, "gridLineColor") or (theme.get("grid") if theme else None) or "#d1d5db"
        grid_width = max(0.0, _advanced_number(settings, "gridLineWidth", 0.8))
        grid_dash = _plotly_grid_line_style(settings)
        x_show = visible and grid_axis in {"x", "both"}
        y_show = visible and grid_axis in {"y", "both"}
        for axis_key, show in (("xaxis", x_show), ("yaxis", y_show)):
            axis = layout.setdefault(axis_key, {})
            axis["showgrid"] = show
            axis["gridcolor"] = grid_color_setting
            axis["gridwidth"] = grid_width
            axis["griddash"] = grid_dash
        scene_grid = {
            "gridcolor": grid_color_setting,
            "gridwidth": grid_width,
            "showgrid": visible,
        }
        layout.setdefault("scene", {}).setdefault("xaxis", {}).update(scene_grid)
        layout.setdefault("scene", {}).setdefault("yaxis", {}).update(scene_grid)
        layout.setdefault("scene", {}).setdefault("zaxis", {}).update(scene_grid)
    if any(
        key in settings
        for key in (
            "axisLineVisible",
            "axisLineColor",
            "axisLineWidth",
            "axisLineTop",
            "axisLineRight",
            "axisLineBottom",
            "axisLineLeft",
        )
    ):
        visible = _advanced_bool(settings, "axisLineVisible", True)
        line_color = _advanced_color_text(settings, "axisLineColor") or (theme.get("axis") if theme else None) or "#111827"
        line_width = max(0.0, _advanced_number(settings, "axisLineWidth", 1.0))
        sides = _advanced_axis_sides(settings)
        x_visible = visible and (sides["bottom"] or sides["top"])
        y_visible = visible and (sides["left"] or sides["right"])
        xaxis = layout.setdefault("xaxis", {})
        xaxis["showline"] = x_visible
        xaxis["linecolor"] = line_color
        xaxis["tickcolor"] = line_color
        xaxis["linewidth"] = line_width
        xaxis["ticks"] = "outside" if x_visible else ""
        if sides["top"] and not sides["bottom"]:
            xaxis["side"] = "top"
        elif sides["top"] and sides["bottom"]:
            xaxis["mirror"] = True

        yaxis = layout.setdefault("yaxis", {})
        yaxis["showline"] = y_visible
        yaxis["linecolor"] = line_color
        yaxis["tickcolor"] = line_color
        yaxis["linewidth"] = line_width
        yaxis["ticks"] = "outside" if y_visible else ""
        if sides["right"] and not sides["left"]:
            yaxis["side"] = "right"
        elif sides["right"] and sides["left"]:
            yaxis["mirror"] = True
        scene_axis = {
            "showline": visible and any(sides.values()),
            "linecolor": line_color,
            "tickcolor": line_color,
            "linewidth": line_width,
        }
        layout.setdefault("scene", {}).setdefault("xaxis", {}).update(scene_axis)
        layout.setdefault("scene", {}).setdefault("yaxis", {}).update(scene_axis)
        layout.setdefault("scene", {}).setdefault("zaxis", {}).update(scene_axis)
    if theme or background or transparent:
        scene_axis = {}
        if theme.get("axis"):
            scene_axis.update({"linecolor": theme["axis"], "tickcolor": theme["axis"]})
        if theme.get("grid"):
            scene_axis["gridcolor"] = theme["grid"]
        scene_background = "rgba(0,0,0,0)" if transparent else background or theme.get("plotly_plot")
        if scene_background:
            scene_axis.update({"showbackground": True, "backgroundcolor": scene_background})
        if scene_axis:
            layout.setdefault("scene", {}).setdefault("xaxis", {}).update(scene_axis)
            layout.setdefault("scene", {}).setdefault("yaxis", {}).update(scene_axis)
            layout.setdefault("scene", {}).setdefault("zaxis", {}).update(scene_axis)
    if legend_size > 0:
        layout.setdefault("legend", {})["font"] = {"size": legend_size}
    if _advanced_element(settings, "titleElement").get("bold"):
        layout.setdefault("title_font", {})["family"] = "Arial Black, Arial, sans-serif"
    elif _advanced_element(settings, "titleElement").get("italic"):
        layout.setdefault("title_font", {})["family"] = "Arial Italic, Arial, sans-serif"
    if _advanced_element(settings, "xLabelElement").get("bold"):
        layout.setdefault("xaxis", {}).setdefault("title", {}).setdefault("font", {})["family"] = "Arial Black, Arial, sans-serif"
    elif _advanced_element(settings, "xLabelElement").get("italic"):
        layout.setdefault("xaxis", {}).setdefault("title", {}).setdefault("font", {})["family"] = "Arial Italic, Arial, sans-serif"
    if _advanced_element(settings, "yLabelElement").get("bold"):
        layout.setdefault("yaxis", {}).setdefault("title", {}).setdefault("font", {})["family"] = "Arial Black, Arial, sans-serif"
    elif _advanced_element(settings, "yLabelElement").get("italic"):
        layout.setdefault("yaxis", {}).setdefault("title", {}).setdefault("font", {})["family"] = "Arial Italic, Arial, sans-serif"
    if font:
        layout["font"] = font
    legend_x = _advanced_number(settings, "legendXOffset", 0.0)
    legend_y = _advanced_number(settings, "legendYOffset", 0.0)
    if legend_x or legend_y:
        layout.setdefault("legend", {})["x"] = 1.02 + _plotly_pixel_fraction(legend_x, width_px)
        layout.setdefault("legend", {})["y"] = 1.0 + _plotly_pixel_fraction(legend_y, height_px)
    return layout


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
    _apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt)


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
    )

    values = diagnostics.overall_observed
    histogram_bin_edges = _imputation_histogram_bin_edges(values, diagnostics.after_imputed)
    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce").replace(0, np.nan)
    draw_components: list[tuple[float, float, int]] = []
    if show_imputation_draw and sample_wise:
        for column in sample_columns:
            column_values = numeric[column]
            missing_count = int(column_values.isna().sum())
            if missing_count <= 0:
                continue
            observed = column_values.dropna().to_numpy(dtype=float)
            if observed.size == 0:
                draw_components.append(
                    (diagnostics.quantile, diagnostics.std * adjust_std, missing_count)
                )
                continue
            column_quantile = float(np.nanquantile(observed, q_value))
            column_std = float(np.nanstd(observed))
            draw_components.append(
                (
                    column_quantile,
                    column_std if column_std > 0 else diagnostics.std,
                    missing_count,
                )
            )
    elif show_imputation_draw:
        draw_components.append(
            (
                diagnostics.quantile,
                diagnostics.std * adjust_std,
                max(1, diagnostics.missing_before),
            )
        )

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

    fig, ax = plt.subplots()
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
    if std_val > 0:
        y = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x - mean_val) / std_val) ** 2)
        ax.plot(x, y, color="red", label="Normal fit")

    if positive_draw_components:
        total_weight = float(sum(weight for _, _, weight in positive_draw_components))
        draw_density = np.zeros_like(x)
        for center, draw_std, weight in positive_draw_components:
            component_density = (
                1 / (draw_std * np.sqrt(2 * np.pi))
            ) * np.exp(-0.5 * ((x - center) / draw_std) ** 2)
            draw_density += (weight / total_weight) * component_density
        ax.plot(x, draw_density, color="cyan", linewidth=2.5, label="Draw area")
    elif draw_components:
        ax.axvline(
            draw_components[0][0],
            color="cyan",
            linewidth=2.5,
            label="Draw area",
        )

    ax.legend()

    ax.set_title("Overall data distribution and norm fit")
    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    _apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt)


def imputation_after_plot(
    kind: AnnotationKind,
    q_value: float,
    adjust_std: float,
    seed: int,
    sample_wise: bool,
    normalization: str = "separate",
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
    )

    non_imputed = diagnostics.after_non_imputed
    imputed = diagnostics.after_imputed
    bin_edges, weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        normalization,
    )

    fig, ax = plt.subplots()
    ax.hist(
        [non_imputed, imputed],
        bins=bin_edges,
        weights=weights,
        alpha=0.6,
        histtype="stepfilled",
        label=["Non-Imputed Values", "Imputed Values"],
    )
    ax.legend()
    ax.set_title("Distribution of data after imputation")
    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    _apply_advanced_axes(ax, advanced)
    return _to_png_bytes(fig, plt)


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


def distribution_qqnorm_plot(kind: AnnotationKind, advanced: dict[str, Any] | None = None) -> bytes:
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
    _apply_advanced_axes(ax, advanced)
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
    advanced: dict[str, Any] | None = None,
) -> bytes:
    plt = _get_plt()
    frame = _coverage_frame(kind).replace(0, np.nan)
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

    title, y_label, red_line_value, _ = _feature_context(frame)
    conditions = meta["condition"].astype(str).dropna().unique().tolist()
    color_map = _advanced_condition_colors(kind, plt, conditions, advanced)

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
                x_pos, y_pos = _advanced_text_position(advanced, bar.get_x() + bar.get_width() / 2, height * 0.02)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{int(np.ceil(height))}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    fontweight="bold",
                    rotation=90,
                    color="black",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels(
            [_advanced_label(condition, advanced, "conditionLabels") for condition in condition_summary["condition"].tolist()],
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
                label=_advanced_label(cond, advanced, "conditionLabels"),
                color=color_map[cond],
            )
            if text:
                for bar in bars:
                    height = float(bar.get_height())
                    if height <= 0:
                        continue
                    x_pos, y_pos = _advanced_text_position(advanced, bar.get_x() + bar.get_width() / 2, height * 0.02)
                    ax.text(
                        x_pos,
                        y_pos,
                        f"{int(np.ceil(height))}",
                        ha="center",
                        va="bottom",
                        fontsize=text_size,
                        fontweight="bold",
                        color="black",
                        rotation=90,
                    )
        ax.set_xticks(positions)
        ax.set_xticklabels(
            [
                _advanced_label(label, advanced, "sampleLabels", sample)
                for label, sample in zip(meta["label"].tolist(), meta["sample"].astype(str).tolist())
            ],
            rotation=90,
            fontsize=6,
        )
        ax.set_xlabel("Condition")
        ymax = float(meta["count"].max()) if not meta.empty else 0.0

    if red_line_value is not None:
        ax.axhline(y=red_line_value, color=_advanced_text(advanced, "referenceLineColor") or "red", linestyle="--")
        ymax = max(ymax, float(red_line_value))

    ax.set_ylabel(y_label)
    if header:
        ax.set_title(title)
    else:
        ax.set_title("")

    if legend and not summary:
        ax.legend(title="Condition", bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        _apply_advanced_axes(ax, advanced)
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        _apply_advanced_axes(ax, advanced)
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
    advanced: dict[str, Any] | None = None,
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
    color_map = _advanced_condition_colors(kind, plt, [condition for condition, _ in mean_intensities], advanced)

    fig, ax = _make_fig(plt, width_cm, height_cm)
    for condition, vals in mean_intensities:
        label = _advanced_label(condition, advanced, "conditionLabels")
        if vals.size < 2 or np.nanstd(vals) <= 0:
            ax.hist(vals, bins=20, density=True, histtype="step", color=color_map[condition], label=label)
            continue
        kde = gaussian_kde(vals)
        density = kde(x_grid)
        ax.plot(x_grid, density, label=label, color=color_map[condition])

    ax.set_xlabel("log2 Intensity")
    ax.set_ylabel("Density")
    if header:
        ax.set_title("Distribution of measured intensity (log2)")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        _apply_advanced_axes(ax, advanced)
        plt.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        _apply_advanced_axes(ax, advanced)
        plt.tight_layout()

    return _to_png_bytes(fig, plt, dpi=dpi)


def qc_peptide_coverage_plot(
    include_id: bool = False,
    header: bool = True,
    legend: bool = True,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Rectangle

    from app.services.peptide_tools import (
        _extract_id_or_number as _extract_peptide_id,
        get_peptide_frame,
    )

    plt = _get_plt()
    frame = get_peptide_frame()
    file_col = _peptide_file_column(frame)
    seq_col = _peptide_sequence_column(frame)
    quantity_col = _peptide_quantity_column(frame)
    meta = _peptide_coverage_metadata(frame, include_id=include_id)

    pivot = frame.pivot_table(
        index=seq_col,
        columns=file_col,
        values=quantity_col,
        aggfunc="max",
    )
    if pivot.empty:
        raise ValueError("No peptide entries are available for coverage plotting.")

    pivot = pivot.copy()
    pivot.columns = [_extract_peptide_id(column) for column in pivot.columns]

    labels = meta["label"].astype(str).tolist()
    rename_map = dict(zip(meta["id"].astype(str), labels))
    pivot = pivot.rename(columns=rename_map)
    selected = [label for label in labels if label in pivot.columns]
    if not selected:
        raise ValueError("Peptide metadata does not match peptide sample columns.")

    data_filtered = pivot[selected].copy()
    summary = data_filtered.notna().sum(axis=0).reset_index()
    summary.columns = ["Sample", "Value"]
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=selected, ordered=True)
    summary = summary.sort_values("Sample")
    peptides_count = int(pivot.shape[0])

    conditions = meta["condition"].astype(str).dropna().tolist()
    ordered_conditions = list(dict.fromkeys(conditions))
    color_map = _advanced_condition_colors("protein", plt, ordered_conditions, advanced)
    sample_to_condition = dict(zip(meta["label"].astype(str), meta["condition"].astype(str)))
    bar_colors = [
        color_map.get(sample_to_condition.get(str(sample), ""), "#1f77b4")
        for sample in summary["Sample"].astype(str).tolist()
    ]

    fig, ax = _make_fig(plt, width_cm, height_cm)
    ax.bar(range(len(summary)), summary["Value"].to_numpy(dtype=float), color=bar_colors)
    ax.axhline(y=peptides_count, color=_advanced_text(advanced, "referenceLineColor") or "red", linestyle="--")
    if header:
        ax.set_title("Peptides per sample")
    ax.set_ylabel("Number of peptides")
    ax.set_xticks(range(len(summary)))
    ax.set_xticklabels(
        [
            _advanced_label(sample, advanced, "sampleLabels", raw_sample)
            for sample, raw_sample in zip(summary["Sample"].astype(str).tolist(), selected)
        ],
        rotation=90,
    )

    if legend and ordered_conditions:
        handles = [Rectangle((0, 0), 1, 1, color=color_map[condition]) for condition in ordered_conditions]
        labels = [_advanced_label(condition, advanced, "conditionLabels") for condition in ordered_conditions]
        ax.legend(handles, labels, title="Condition", bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")

    _apply_advanced_axes(ax, advanced)
    fig.tight_layout()
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
    advanced: dict[str, Any] | None = None,
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
    color_map = _advanced_condition_colors(kind, plt, conditions, advanced)
    box_border_color = _advanced_text(advanced, "boxBorderColor") or "black"
    box_median_color = _advanced_text(advanced, "boxMedianColor") or "firebrick"
    box_outlier_color = _advanced_text(advanced, "boxOutlierColor") or "red"
    box_outlier_edge_color = _advanced_text(advanced, "boxOutlierEdgeColor") or "black"
    box_outlier_size = max(1.0, _advanced_number(advanced, "boxOutlierSize", 5.0))
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
                x_pos, y_pos = _advanced_text_position(advanced, i + 1, median * 1.02)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{median:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    rotation=0,
                    color="black",
                    fontweight="bold",
                )

        ax.set_xticks(range(1, len(samples) + 1))
        ax.set_xticklabels(
            [
                _advanced_label(sample, advanced, "sampleLabels", raw_sample)
                for sample, raw_sample in zip(samples, meta["sample"].astype(str).tolist())
            ],
            rotation=90,
            ha="center",
        )
        ax.set_ylabel("log2 Intensity")
        if header:
            ax.set_title("Measured intensity values (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor=box_border_color, label=_advanced_label(c, advanced, "conditionLabels"))
                for c in conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=_advanced_anchor(ax, advanced, 1, 0.5))
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
                x_pos, y_pos = _advanced_text_position(advanced, pos, med * 1.02)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{med:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=text_size,
                    color="black",
                    rotation=0,
                    fontweight="bold",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels([_advanced_label(condition, advanced, "conditionLabels") for condition in valid_conditions])
        ax.set_xlabel("Condition")
        ax.set_ylabel("log2 Intensity")
        if header:
            ax.set_title("Measured intensity values (log2)")
        else:
            ax.set_title("")

        if legend:
            legend_handles = [
                Patch(facecolor=color_map[c], edgecolor=box_border_color, label=_advanced_label(c, advanced, "conditionLabels"))
                for c in valid_conditions
            ]
            ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=_advanced_anchor(ax, advanced, 1, 0.5))
            _apply_advanced_axes(ax, advanced)
            plt.tight_layout(rect=[0, 0, 0.85, 1])

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        _apply_advanced_axes(ax, advanced)
        plt.tight_layout()
    elif str(mode).lower() == "single":
        _apply_advanced_axes(ax, advanced)

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
    frame = _original_scale_frame(kind).replace(0, np.nan)
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

    color_map = _advanced_condition_colors(kind, plt, valid_conditions, advanced)
    box_border_color = _advanced_text(advanced, "boxBorderColor") or "black"
    box_median_color = _advanced_text(advanced, "boxMedianColor") or "firebrick"
    box_outlier_color = _advanced_text(advanced, "boxOutlierColor") or "red"
    box_outlier_edge_color = _advanced_text(advanced, "boxOutlierEdgeColor") or "black"
    box_outlier_size = max(1.0, _advanced_number(advanced, "boxOutlierSize", 5.0))
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
            x_pos, y_pos = _advanced_text_position(advanced, i, med)
            ax.text(x_pos, y_pos, f"{med:.2f}", ha="center", va="bottom", fontsize=text_size, fontweight="bold", color="black")

    ax.set_xticks(positions)
    ax.set_xticklabels([_advanced_label(condition, advanced, "conditionLabels") for condition in valid_conditions])
    ax.set_xlabel("Condition")
    ax.set_ylabel("Coefficient of Variation (%)")
    if header:
        ax.set_title("Coefficient of Variation")
    else:
        ax.set_title("")

    if legend:
        legend_handles = [
            Patch(facecolor=color_map[c], edgecolor=box_border_color, label=_advanced_label(c, advanced, "conditionLabels"))
            for c in valid_conditions
        ]
        ax.legend(handles=legend_handles, title="Condition", loc="center left", bbox_to_anchor=_advanced_anchor(ax, advanced, 1, 0.5))
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    _apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _pca_feature_matrix(numeric: pd.DataFrame, *, n_components: int) -> pd.DataFrame:
    complete = numeric.dropna()
    if complete.shape[0] >= n_components:
        return complete

    sample_count = int(numeric.shape[1])
    observed_counts = numeric.notna().sum(axis=1)
    candidate_thresholds = sorted(
        {
            min(sample_count, max(2, int(np.ceil(sample_count * fraction))))
            for fraction in (0.8, 0.5, 0.2)
        }
        | {2},
        reverse=True,
    )

    for min_present in candidate_thresholds:
        candidate = numeric.loc[observed_counts >= min_present].copy()
        if candidate.shape[0] < n_components:
            continue
        row_means = candidate.mean(axis=1)
        candidate = candidate.T.fillna(row_means).T
        if candidate.shape[0] >= n_components and not candidate.isna().any().any():
            return candidate

    raise ValueError(
        "No sufficiently observed feature rows are available for dimensionality reduction."
    )


def _pca_projection(
    kind: AnnotationKind,
    plot_dim: str = "2D",
    method: str = "PCA",
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    tsne_perplexity: float = 30.0,
    tsne_learning_rate: float = 200.0,
    random_state: int = 42,
) -> tuple[pd.DataFrame, np.ndarray | None, str]:
    frame = _log2_qc_frame(kind)
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
    x_std = x_centered.std(axis=0, keepdims=True)
    x_std[x_std == 0] = 1.0
    x_scaled = x_centered / x_std

    explained: np.ndarray | None = None
    axis_prefix = "PC"

    if method_key == "pca":
        u, s, _ = np.linalg.svd(x_centered, full_matrices=False)
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
        scores = reducer.fit_transform(x_scaled)
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
        scores = tsne.fit_transform(x_scaled)
        axis_prefix = "t-SNE"
    else:
        raise ValueError("Unsupported dimensionality-reduction method. Use PCA, UMAP, or t-SNE.")

    pcs = [f"{axis_prefix}{i + 1}" for i in range(n_components)]
    pca_scores = pd.DataFrame(scores, columns=pcs)
    pca_scores["sample"] = transposed_expr.index.astype(str)
    condition_map = meta.set_index("sample")["condition"].astype(str).to_dict()
    pca_scores["condition"] = pca_scores["sample"].map(condition_map).fillna("sample")
    return pca_scores, explained, axis_prefix


def _compute_cluster_labels(
    embedding: np.ndarray,
    *,
    cluster_method: str = "None",
    cluster_count: int = 3,
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
) -> np.ndarray | None:
    method_key = str(cluster_method or "None").strip().lower()
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
        model = DBSCAN(
            eps=max(1e-6, float(dbscan_eps)),
            min_samples=max(1, int(dbscan_min_samples)),
        )
        return model.fit_predict(embedding)

    raise ValueError("Unsupported clustering method. Use None, KMeans, Agglomerative, or DBSCAN.")


def _cluster_display_label(label: int) -> str:
    if int(label) == -1:
        return "Noise"
    return f"Cluster {int(label) + 1}"


def qc_pca_plot(
    kind: AnnotationKind,
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
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    from matplotlib.patches import Ellipse

    plt = _get_plt()
    pca_scores, explained, axis_prefix = _pca_projection(
        kind,
        plot_dim=plot_dim,
        method=method,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        random_state=random_state,
    )
    n_components = 3 if str(plot_dim).upper() == "3D" else 2
    component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]

    cluster_labels = _compute_cluster_labels(
        pca_scores[component_cols].to_numpy(dtype=float),
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        dbscan_eps=dbscan_eps,
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
    color_map = _advanced_condition_colors(kind, plt, groups, advanced)
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
                label=_advanced_label(group, advanced, "conditionLabels"),
                s=max(1, dot_size) * 10,
                alpha=0.7,
                color=color_map[group],
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
                bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1),
                loc="upper left",
            )
    else:
        fig, ax = _make_fig(plt, width_cm, height_cm)
        for group in groups:
            subset = pca_scores[pca_scores[group_col] == group]
            ax.scatter(
                subset[component_cols[0]],
                subset[component_cols[1]],
                label=_advanced_label(group, advanced, "conditionLabels"),
                s=max(1, dot_size) * 10,
                alpha=0.7,
                color=color_map[group],
            )
            if add_ellipses and len(subset) > 2:
                points = subset[[component_cols[0], component_cols[1]]].to_numpy()
                center, axes, angle = _minimum_enclosing_ellipse(points)
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
                bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1),
                loc="upper left",
            )

    if not legend:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()

    _apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def qc_pca_interactive_html(
    kind: AnnotationKind,
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
    dbscan_eps: float = 0.5,
    dbscan_min_samples: int = 2,
    random_state: int = 42,
    width_cm: float = 20,
    height_cm: float = 10,
    advanced: dict[str, Any] | None = None,
) -> str:
    px, go = _get_plotly()
    pca_scores, explained, axis_prefix = _pca_projection(
        kind,
        plot_dim=plot_dim,
        method=method,
        umap_n_neighbors=umap_n_neighbors,
        umap_min_dist=umap_min_dist,
        tsne_perplexity=tsne_perplexity,
        tsne_learning_rate=tsne_learning_rate,
        random_state=random_state,
    )
    plot_3d = str(plot_dim).upper() == "3D"
    n_components = 3 if plot_3d else 2
    component_cols = [f"{axis_prefix}{i + 1}" for i in range(n_components)]

    height_px = _cm_to_px(height_cm)
    cluster_labels = _compute_cluster_labels(
        pca_scores[component_cols].to_numpy(dtype=float),
        cluster_method=cluster_method,
        cluster_count=cluster_count,
        dbscan_eps=dbscan_eps,
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
    color_map = _advanced_condition_colors(kind, None, groups, advanced)
    display_col = f"{color_col}_display"
    pca_scores[display_col] = pca_scores[color_col].astype(str).map(
        lambda value: _advanced_label(value, advanced, "conditionLabels")
    )
    display_color_map = {
        _advanced_label(group, advanced, "conditionLabels"): color_map[group]
        for group in groups
    }
    method_name = "t-SNE" if str(method).strip().lower() in {"t-sne", "tsne", "t_sne"} else str(method).strip().upper()

    hover_data = {"sample": True, "condition": True}
    if cluster_labels is not None:
        hover_data["cluster"] = True

    if plot_3d:
        fig = px.scatter_3d(
            pca_scores,
            x=component_cols[0],
            y=component_cols[1],
            z=component_cols[2],
            color=display_col,
            color_discrete_map=display_color_map,
            hover_data=hover_data,
            opacity=0.85,
        )
        fig.update_traces(marker=dict(size=max(2, int(dot_size))))
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
            ),
            legend_title_text="Cluster" if color_col == "cluster" else "Condition",
        )
        scene_overrides: dict[str, Any] = {}
        x_override = _advanced_text(advanced, "xLabel")
        y_override = _advanced_text(advanced, "yLabel")
        if x_override is not None:
            scene_overrides["xaxis_title"] = x_override
        if y_override is not None:
            scene_overrides["yaxis_title"] = y_override
        if scene_overrides:
            fig.update_layout(scene=scene_overrides)
        fig.update_layout(**_advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))
        return _plotly_html(fig)

    fig = px.scatter(
        pca_scores,
        x=component_cols[0],
        y=component_cols[1],
        color=display_col,
        color_discrete_map=display_color_map,
        hover_data=hover_data,
        opacity=0.85,
    )
    fig.update_traces(marker=dict(size=max(2, int(dot_size))))
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
    fig.update_layout(**_advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))

    if add_ellipses:
        for group in groups:
            subset = pca_scores[pca_scores[color_col] == group]
            if len(subset) <= 2:
                continue
            points = subset[[component_cols[0], component_cols[1]]].to_numpy()
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
    frame = _original_scale_frame(kind).replace(0, np.nan)
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
        mean_intensities[cond] = np.log10(means + 1)
        valid_conditions.append(cond)

    if not valid_conditions:
        raise ValueError("No conditions available for abundance plot.")

    if len(valid_conditions) > 1:
        keep_mask = mean_intensities[valid_conditions].isna().sum(axis=1) < (len(valid_conditions) - 1)
        mean_intensities = mean_intensities.loc[keep_mask]
    else:
        mean_intensities = mean_intensities.dropna(subset=[valid_conditions[0]])

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

    color_map = _advanced_condition_colors(kind, plt, unique_conditions, advanced)
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
                label=_advanced_label(cond, advanced, "conditionLabels"),
                color=color_map[cond],
                s=5,
            )
    else:
        if condition not in unique_conditions:
            raise ValueError(f"Condition '{condition}' not found.")
        values = mean_intensities[condition].dropna().sort_values(ascending=False).reset_index(drop=True)
        ranks = np.arange(1, len(values) + 1)
        ax.scatter(
            ranks,
            values.values,
            label=_advanced_label(condition, advanced, "conditionLabels"),
            color=color_map[condition],
            s=7,
        )

    ax.set_xlabel(f"{workflow} Rank")
    ax.set_ylabel(f"log10 {workflow} Intensity")
    if header:
        ax.set_title(f"Abundance plot - {workflow}")
    else:
        ax.set_title("")

    if legend:
        ax.legend(title="Condition", bbox_to_anchor=_advanced_anchor(ax, advanced, 1.05, 1), loc="upper left")
        _apply_advanced_axes(ax, advanced)
        fig.tight_layout(rect=[0, 0, 0.85, 1])
    else:
        legend_obj = ax.get_legend()
        if legend_obj is not None:
            legend_obj.remove()
        _apply_advanced_axes(ax, advanced)
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
    color_map = _advanced_condition_colors(kind, None, visible_conditions, advanced)
    long_intensities = long_intensities.copy()
    long_intensities["ConditionDisplay"] = long_intensities["Condition"].astype(str).map(
        lambda value: _advanced_label(value, advanced, "conditionLabels")
    )
    display_color_map = {
        _advanced_label(condition, advanced, "conditionLabels"): color_map[condition]
        for condition in visible_conditions
    }

    fig = px.scatter(
        long_intensities,
        x="Rank",
        y="log10Intensity",
        color="ConditionDisplay",
        color_discrete_map=display_color_map,
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
    fig.update_layout(**_advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))
    return _plotly_html(fig)


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
    frame = _original_scale_frame(kind)
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
    cmap_name = _advanced_text(advanced, "correlationColorMap") or "coolwarm"
    if cmap_name not in color_map_options:
        cmap_name = "coolwarm"
    cmap = plt.get_cmap(cmap_name)
    color_norm = plt.Normalize(vmin=vmin, vmax=vmax)
    method_normalized = str(method).strip().lower()
    x_labels = [
        _advanced_label(label, advanced, "sampleLabels", original_by_label.get(str(label)))
        for label in ordered_corr.columns.tolist()
    ]
    y_labels = [
        _advanced_label(label, advanced, "sampleLabels", original_by_label.get(str(label)))
        for label in ordered_corr.index.tolist()
    ]
    if method_normalized == "matrix":
        cax = ax.matshow(ordered_corr, cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_xticks(range(len(ordered_corr.columns)))
        ax.set_yticks(range(len(ordered_corr.index)))
        ax.set_xticklabels(x_labels, rotation=90, ha="center", va="bottom", fontsize=7)
        ax.set_yticklabels(y_labels, fontsize=7)
        fig.colorbar(cax, ax=ax, fraction=0.046, pad=0.04)
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
                ellipse = Ellipse(
                    (j + 0.5, i + 0.5),
                    width=0.9,
                    height=0.9 * (1 - abs(r)),
                    angle=45 if r > 0 else -45,
                    facecolor=cmap(color_norm(r)),
                    alpha=0.6,
                )
                ax.add_patch(ellipse)

        sm = plt.cm.ScalarMappable(cmap=cmap, norm=color_norm)
        fig.colorbar(sm, ax=ax, fraction=0.046, pad=0.04)
    else:
        raise ValueError("method must be 'Matrix' or 'Ellipse'")

    ax.set_xlabel("Samples")
    ax.set_ylabel("Samples")
    _apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)

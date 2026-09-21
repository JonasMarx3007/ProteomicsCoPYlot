from __future__ import annotations

from app.services.html_security import GENERATED_HTML_META
from app.services.plot_webgl import force_svg_rendering

from app.services.plot_export import (
    to_png_bytes as _to_png_bytes,
    cm_to_inch as _cm_to_inch,
)

import json
import math
import re
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.condition_palette_store import build_condition_color_map
from app.services.data_tools import _get_current_frame, _get_sample_columns, require_imputable_kind, original_intensity_frame
from app.services.functions import (
    _phosprot_values_are_centred,
    intensity_unit_label,
    resolve_feature_scaling,
    abundance_axis_label,
    qc_matrix,
    select_matrix,
    choose_best_source,
    extract_sample_id as _extract_id_or_number,
    impute_values_with_diagnostics,
    QQ_MAX_POINTS,
    qqnorm_plot_data,
    raw_zero_to_nan,
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
    fig = force_svg_rendering(fig)
    bg = _plotly_html_background(fig)
    body = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "responsive": True},
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"{GENERATED_HTML_META}"
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
    require_imputable_kind(kind)
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    filtered = annotation.filtered_data if annotation is not None else None
    log2 = annotation.log2_data if annotation is not None else None
    source_name, frame = choose_best_source(filtered, log2, raw)
    if source_name == "raw" and not bool(
        getattr(annotation, "is_log2_transformed", False)
    ):
        frame = raw_zero_to_nan(frame, _get_sample_columns(kind, frame))
    return source_name, frame


def _original_scale_frame(kind: AnnotationKind):
    return original_intensity_frame(_get_current_frame(kind), get_annotation(kind))


def _distribution_frame(kind: AnnotationKind):
    return qc_matrix(kind)[0]


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


def _peptide_quantity_column(frame: pd.DataFrame, requested: str | None = None) -> str:
    # Kept as a private compatibility alias for AI/report callers. The actual
    # policy lives in one shared in-app resolver.
    from app.services.peptide_quantity import resolve_peptide_quantity_column

    return resolve_peptide_quantity_column(frame, requested=requested)


def _peptide_coverage_metadata(frame: pd.DataFrame, include_id: bool) -> pd.DataFrame:
    # Reuse the exact metadata preparation used by peptide modification/missed-cleavage
    # so peptide coverage follows the same shared proteome metadata behavior.
    from app.services.peptide_tools import _prepare_metadata as _prepare_peptide_metadata

    meta = _prepare_peptide_metadata(frame, include_id=include_id).copy()
    return meta.rename(columns={"new_sample": "label"})


def _coverage_frame(kind: AnnotationKind):
    return qc_matrix(kind)[0]


def _log2_qc_frame(kind: AnnotationKind):
    return qc_matrix(kind)[0]


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


def advanced_color(settings: dict[str, Any] | None, key: str, default: str) -> str:
    """A colour the advanced panel may override, falling back to the plot's own.

    Every colour picker that used to sit in a plot's normal options row reaches
    its renderer through one of these, so the picker can move into the advanced
    panel without each route growing another parameter.
    """
    return _advanced_color_text(settings, key) or default


def advanced_label_size(settings: dict[str, Any] | None, default: float) -> float:
    """The size of the value labels drawn on bars and boxes.

    Was a per-page "Text Size" field, clamped 6-20 on one page, 6-24 on another
    and unbounded on a third. One setting, one floor.
    """
    return max(4.0, _advanced_number(settings, "valueLabelSize", default))


def marker_area(diameter: float) -> float:
    """Matplotlib's `s` for a marker of the given diameter in points.

    Every dot size in this tool is expressed as a **diameter in points**, so one
    number means the same dot whichever renderer draws it. Matplotlib wants an
    area in points squared, plotly wants the diameter, and the conversion is
    just the square -- `sqrt(s)` is the marker's width in points.

    Before this existed each plot invented its own scale: the PCA multiplied the
    setting by 10, the correlation scatter took its square root, and the two
    routes behind one control declared different defaults (5 and 8, 60 and 8).
    A "dot size" of 60 therefore drew a different dot on every page.
    """
    return max(1.0, float(diameter)) ** 2


def _advanced_size(settings: dict[str, Any] | None, key: str, default: float) -> float:
    """A marker diameter from the advanced settings, floored at something visible."""
    return max(0.5, _advanced_number(settings, key, default))


# One name per shape, and the spelling each renderer wants for it. A shape set
# in the advanced panel has to draw the same marker in the figure and in the
# interactive plot beside it, and matplotlib and plotly agree on none of their
# own names -- so the panel's vocabulary is neither of theirs.
MARKER_SHAPES: dict[str, tuple[str, str]] = {
    # name:        (matplotlib, plotly)
    "circle": ("o", "circle"),
    "square": ("s", "square"),
    "diamond": ("D", "diamond"),
    "triangle-up": ("^", "triangle-up"),
    "triangle-down": ("v", "triangle-down"),
    "cross": ("P", "cross"),
    "x": ("X", "x"),
    "star": ("*", "star"),
    "pentagon": ("p", "pentagon"),
    "hexagon": ("h", "hexagon"),
}
DEFAULT_MARKER_SHAPE = "circle"

# The per-condition override maps, and the general key each one falls back to.
# Read together by `marker_style`, written together by the panel: choosing a
# general value clears the map beside it, so every group snaps to the new value
# and can then be moved off it again one at a time.
_CONDITION_MARKER_KEYS: dict[str, str] = {
    "conditionMarkerSizes": "markerSize",
    "conditionMarkerShapes": "markerShape",
    "conditionMarkerAlphas": "markerAlpha",
    "conditionMarkerEdgeWidths": "markerEdgeWidth",
    "conditionMarkerEdgeColors": "markerEdgeColor",
}


def _group_override(
    settings: dict[str, Any] | None, map_key: str, group: str | None
) -> Any:
    """This group's entry in one override map, or None."""
    if not settings or group is None:
        return None
    mapping = settings.get(map_key)
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(str(group))
    return value if value not in (None, "") else None



def advanced_color_map(settings: dict[str, Any] | None, default: str) -> str:
    """The colour scale the panel asks for, or this plot's own.

    An unknown name falls back rather than raising: the field is free text, and
    a half-typed colour map should not replace the figure with a 400 while the
    user is still typing it.
    """
    name = _advanced_text(settings, "correlationColorMap")
    if not name:
        return default
    try:
        import matplotlib

        matplotlib.colormaps[str(name)]
    except (KeyError, ValueError, ImportError):
        return default
    return str(name)


def resolve_marker_shape(name: Any, renderer: str = "matplotlib") -> str:
    """One shape name, in the renderer's own spelling."""
    key = str(name or DEFAULT_MARKER_SHAPE).strip().lower()
    matplotlib_name, plotly_name = MARKER_SHAPES.get(
        key, MARKER_SHAPES[DEFAULT_MARKER_SHAPE]
    )
    return plotly_name if renderer == "plotly" else matplotlib_name


@dataclass
class MarkerAppearance:
    """One class of dot, fully resolved: general settings, then this group's."""

    diameter: float
    alpha: float
    edge_width: float
    edge_color: str
    shape: str
    color: str | None

    def matplotlib(self) -> dict[str, Any]:
        style: dict[str, Any] = {
            "s": marker_area(self.diameter),
            "alpha": self.alpha,
            "linewidths": self.edge_width,
            "edgecolors": self.edge_color if self.edge_width > 0 else "none",
            "marker": resolve_marker_shape(self.shape),
        }
        if self.color:
            style["color"] = self.color
        return style

    def plotly(self, *, with_opacity: bool = True) -> dict[str, Any]:
        marker: dict[str, Any] = {
            "size": self.diameter,
            "symbol": resolve_marker_shape(self.shape, "plotly"),
        }
        if with_opacity:
            marker["opacity"] = self.alpha
        if self.color:
            marker["color"] = self.color
        if self.edge_width > 0:
            marker["line"] = {"width": self.edge_width, "color": self.edge_color}
        return marker


def resolve_marker(
    settings: dict[str, Any] | None,
    *,
    size: float,
    alpha: float,
    group: str | None = None,
    color: str | None = None,
    color_default: str | None = None,
    use_color: bool = True,
    size_key: str = "markerSize",
    alpha_key: str = "markerAlpha",
    edge_width_key: str = "markerEdgeWidth",
    edge_color_key: str = "markerEdgeColor",
    edge_width_default: float = 0.0,
    edge_color_default: str = "#000000",
) -> MarkerAppearance:
    """A dot's appearance: the plot's default, then the general setting, then this group's.

    `group` names the class being drawn -- a condition on a PCA or an abundance
    curve, a significance class on a volcano. `color` is the colour the plot has
    already decided on, usually from the condition palette; it wins over the
    general `markerColor`, because a condition's colour is set in the colours
    card and nowhere else. `color_default` is what to fall back to when neither
    is given.

    The `*_key` arguments let a plot name its own general keys: the
    single-protein boxplot's jittered points have had `boxPointSize` and friends
    since before this existed, and they are that plot's general layer.

    `use_color=False` is for a plot that colours its points from the data --
    a colour-mapped scatter cannot also be handed one colour, and a general
    `markerColor` must not turn its colour bar into a flat wash.
    """
    size_override = _group_override(settings, "conditionMarkerSizes", group)
    diameter = (
        max(0.5, float(size_override))
        if size_override is not None
        else _advanced_size(settings, size_key, size)
    )

    alpha_override = _group_override(settings, "conditionMarkerAlphas", group)
    opacity = (
        min(1.0, max(0.0, float(alpha_override)))
        if alpha_override is not None
        else _advanced_alpha(settings, alpha_key, alpha)
    )

    edge_width = _group_override(settings, "conditionMarkerEdgeWidths", group)
    if edge_width is None:
        edge_width = _advanced_number(settings, edge_width_key, edge_width_default)
    edge_width = max(0.0, float(edge_width))

    edge_color = _group_override(settings, "conditionMarkerEdgeColors", group)
    if edge_color is None:
        edge_color = _advanced_text(settings, edge_color_key)

    shape = _group_override(settings, "conditionMarkerShapes", group)
    if shape is None:
        shape = _advanced_text(settings, "markerShape")

    resolved_color = (
        (color or advanced_color(settings, "markerColor", "") or color_default)
        if use_color
        else None
    )
    return MarkerAppearance(
        diameter=diameter,
        alpha=opacity,
        edge_width=edge_width,
        edge_color=str(edge_color or edge_color_default),
        shape=str(shape or DEFAULT_MARKER_SHAPE),
        color=resolved_color,
    )


def marker_style(
    settings: dict[str, Any] | None,
    *,
    size: float,
    alpha: float,
    group: str | None = None,
    color: str | None = None,
    color_default: str | None = None,
    use_color: bool = True,
    edge_width_default: float = 0.0,
    edge_color_default: str = "#000000",
) -> dict[str, Any]:
    """Matplotlib scatter kwargs for one class of dot.

    The outline is off unless asked for, because an outline on a scatter of
    eight thousand points fills the figure with ink.
    """
    return resolve_marker(
        settings,
        size=size,
        alpha=alpha,
        group=group,
        color=color,
        color_default=color_default,
        use_color=use_color,
        edge_width_default=edge_width_default,
        edge_color_default=edge_color_default,
    ).matplotlib()


def plotly_marker(
    settings: dict[str, Any] | None,
    *,
    size: float,
    alpha: float | None = None,
    group: str | None = None,
    color: str | None = None,
    color_default: str | None = None,
    use_color: bool = True,
    edge_width_default: float = 0.0,
    edge_color_default: str = "#000000",
) -> dict[str, Any]:
    """The same resolution, as a plotly `marker` dict."""
    appearance = resolve_marker(
        settings,
        size=size,
        alpha=alpha if alpha is not None else 1.0,
        group=group,
        color=color,
        color_default=color_default,
        use_color=use_color,
        edge_width_default=edge_width_default,
        edge_color_default=edge_color_default,
    )
    return appearance.plotly(with_opacity=alpha is not None)



def apply_plotly_group_markers(
    fig: Any,
    settings: dict[str, Any] | None,
    *,
    size: float,
    alpha: float | None = None,
    display_to_group: dict[str, str] | None = None,
    colors: dict[str, str] | None = None,
) -> None:
    """Give each trace the marker its own group resolves to.

    Plotly express makes one trace per group and names it with whatever the
    frame was coloured by -- which on these plots is the *display* label, after
    any renaming. The override maps are keyed by the real condition name, so the
    display label has to be translated back before it is looked up, or renaming
    a condition would quietly drop its point settings.
    """
    lookup = display_to_group or {}

    def update(trace: Any) -> None:
        name = str(getattr(trace, "name", "") or "")
        group = lookup.get(name, name)
        trace.update(
            marker=plotly_marker(
                settings,
                size=size,
                alpha=alpha,
                group=group,
                color=(colors or {}).get(group),
            )
        )

    fig.for_each_trace(update)


def _pca_default_size(dot_size: float) -> float:
    """The old `dotSize` number, read as a diameter.

    The projection's legacy control multiplied its value by 10 for matplotlib
    and passed it raw to plotly, so the two renderers drew different dots from
    one setting. The number now means a diameter in both, and the historical
    default of 5 lands on a dot of about the size it used to draw.
    """
    return max(1.0, float(dot_size)) * 1.2


def plotly_marker_size(settings: dict[str, Any] | None, default: float) -> float:
    """The same diameter, for the plotly side of a plot that has both."""
    return _advanced_size(settings, "markerSize", default)


def _advanced_alpha(settings: dict[str, Any] | None, key: str, default: float) -> float:
    """An opacity from the advanced settings, clamped to the range that exists."""
    return min(1.0, max(0.0, _advanced_number(settings, key, default)))


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


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #

# The faces a figure may be drawn in, and what each renderer has to be told to
# get one. Journals ask for Arial, Helvetica or Times New Roman; what is
# installed in this image is the Liberation family, whose metrics are identical
# to those three, so a figure drawn here measures the same as one drawn on a
# machine that has the originals.
#
# Every list ends at a DejaVu face, which ships with matplotlib. A family name
# matplotlib cannot resolve is a warning on stderr and a silent substitution --
# the figure comes back in the wrong face and nothing in the response says so --
# and ending each list at something that is certainly present means there is
# never anything to substitute.
PLOT_FONTS: dict[str, tuple[tuple[str, ...], str]] = {
    # name:          (matplotlib family list,                       plotly CSS stack)
    "helvetica": (
        ("Liberation Sans", "Helvetica", "Arial", "DejaVu Sans"),
        "Helvetica, Arial, 'Liberation Sans', sans-serif",
    ),
    "times": (
        ("Liberation Serif", "Times New Roman", "Times", "DejaVu Serif"),
        "'Times New Roman', Times, 'Liberation Serif', serif",
    ),
    "courier": (
        ("Liberation Mono", "Courier New", "Courier", "DejaVu Sans Mono"),
        "'Courier New', Courier, 'Liberation Mono', monospace",
    ),
    "dejavu-sans": (("DejaVu Sans",), "'DejaVu Sans', Verdana, sans-serif"),
    "dejavu-serif": (("DejaVu Serif",), "'DejaVu Serif', Georgia, serif"),
}

# The one global key, and the element that may disagree with it. An element key
# left unset -- or set to the empty string, which is what the panel's "Same as
# all text" option sends -- follows the global one, so the common case is a
# single choice and the exception costs one more.
FONT_KEY = "fontFamily"
FONT_ELEMENT_KEYS: dict[str, str] = {
    "title": "titleFontFamily",
    "axisLabel": "axisLabelFontFamily",
    "tick": "tickFontFamily",
    "legend": "legendFontFamily",
    "valueLabel": "valueLabelFontFamily",
}


def resolve_font(
    settings: dict[str, Any] | None, element: str | None = None
) -> tuple[tuple[str, ...], str] | None:
    """The face this element should be drawn in, or None to leave it alone.

    None is not the same as a default: no font setting at all means the renderer
    never touches the family, so every plot keeps whatever it had before this
    existed. Only an explicit choice changes anything.
    """
    for key in ([FONT_ELEMENT_KEYS[element]] if element in FONT_ELEMENT_KEYS else []) + [FONT_KEY]:
        name = _advanced_text(settings, key)
        if name and name in PLOT_FONTS:
            return PLOT_FONTS[name]
    return None


@lru_cache(maxsize=None)
def installed_family(families: tuple[str, ...]) -> str:
    """The first of these faces that is actually installed.

    Handing matplotlib the whole list works, but it logs a `findfont: Font
    family 'Arial' not found` line for every name it steps over -- on a server
    where the Liberation clones are what is installed, that is three lines of
    noise per figure for a lookup that succeeded. Resolving once, here, keeps
    the preference order (a machine that really has Arial gets Arial) and says
    nothing when it falls through to the clone.
    """
    from matplotlib import font_manager  # noqa: PLC0415 -- import cost, once

    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in families:
        if name in available:
            return name
    # Nothing matched: hand back the last name, which is a DejaVu face shipped
    # with matplotlib, so the substitution is the one that would have happened
    # anyway rather than a hard failure in the middle of a render.
    return families[-1]


def mpl_font_family(settings: dict[str, Any] | None, element: str | None = None) -> list[str] | None:
    """`set_fontfamily` argument for this element, or None to leave it alone."""
    font = resolve_font(settings, element)
    return [installed_family(font[0])] if font else None


def plotly_font_family(settings: dict[str, Any] | None, element: str | None = None) -> str | None:
    """`font.family` for this element, or None to leave it alone."""
    font = resolve_font(settings, element)
    return font[1] if font else None


def verify_fonts_installed() -> str:
    """Prove every offered face resolves to a file, and warm the font cache.

    Run at image build time. A family matplotlib cannot find is not an error at
    render time -- it warns once, substitutes DejaVu and draws the figure -- so
    without this the panel could offer five fonts and produce one, and the only
    evidence would be a line in a log nobody reads. Building the cache here also
    keeps the first plot of a container's life from paying for it.

    Returns a line naming what was found, so the build log says it out loud.
    """
    plt = _get_plt()
    from matplotlib import font_manager  # noqa: PLC0415 -- build-time only

    available = {font.name for font in font_manager.fontManager.ttflist}
    missing = {
        name: families[0] for name, (families, _) in PLOT_FONTS.items() if families[0] not in available
    }
    if missing:
        raise RuntimeError(
            "fonts offered by the advanced panel are not installed in this image: "
            + ", ".join(f"{name} needs {face}" for name, face in sorted(missing.items()))
            + ". Install them (fonts-liberation, fonts-dejavu-core) or take them out of PLOT_FONTS."
        )
    figure, axes = plt.subplots(figsize=(1, 1))
    for families, _ in PLOT_FONTS.values():
        axes.set_title("Ag", fontfamily=installed_family(families))
        figure.canvas.draw()
    plt.close(figure)
    return "fonts ok: " + ", ".join(sorted(families[0] for families, _ in PLOT_FONTS.values()))


def _set_font_family(artist: Any, family: list[str] | None) -> None:
    """Set a matplotlib text artist's family, tolerating one that has none."""
    if family is None or artist is None:
        return
    setter = getattr(artist, "set_fontfamily", None)
    if setter is None:
        return
    setter(family)


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


_LINE_STYLE_NAMES = {"solid", "dashed", "dotted", "dashdot"}
_MPL_LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dashdot": "-."}
_PLOTLY_LINE_STYLES = {"solid": "solid", "dashed": "dash", "dotted": "dot", "dashdot": "dashdot"}


@dataclass(frozen=True)
class ReferenceLine:
    """How to draw a threshold or guide line, for either renderer.

    Every plot in this tool that draws a line over its data -- the coverage
    plot's total, a volcano's fold-change and p-value thresholds, a Q-Q fit, an
    identity line, a regression fit, the imputation draw area -- used to hardcode
    its own colour, dash and width. Two of them read a colour from the advanced
    panel and their interactive twins ignored it, so the same figure changed
    appearance when you switched renderer.

    They all come through here now. `visible` is what the panel's switch sets,
    and the defaults are each plot's own, so nothing looks different until
    somebody changes something.
    """

    visible: bool
    color: str
    style: str
    width: float

    def matplotlib(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "linestyle": _MPL_LINE_STYLES.get(self.style, "--"),
            "linewidth": self.width,
        }

    def plotly(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "dash": _PLOTLY_LINE_STYLES.get(self.style, "dash"),
            "width": self.width,
        }


def resolve_reference_line(
    settings: dict[str, Any] | None,
    *,
    color: str = "red",
    style: str = "dashed",
    width: float = 1.5,
) -> ReferenceLine:
    """The reference line for this plot: the panel's choice, else the plot's own."""
    return ReferenceLine(
        visible=_advanced_bool(settings, "referenceLineVisible", True),
        color=_advanced_color_text(settings, "referenceLineColor") or color,
        style=_advanced_choice(settings, "referenceLineStyle", _LINE_STYLE_NAMES, style),
        width=max(0.0, _advanced_number(settings, "referenceLineWidth", width)),
    )


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
    colour = str(element.get("color") or "").strip()
    if colour:
        props["color"] = colour
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


def _rename_composite_sample_label(
    label: str,
    sample: str,
    condition: str,
    settings: dict[str, Any] | None,
) -> str:
    """A `Condition_1` tick label, with the condition part renamed.

    These labels are built by pasting the condition name in front of a replicate
    number, so they are invisible to the `conditionLabels` map -- it is keyed by
    the condition, and the tick says `Control_1`. The result was a plot whose
    legend read the new name while its x-axis still read the old one, which is
    the same group under two names in one figure.

    A `sampleLabels` override still wins: it names one sample, which is more
    specific than renaming its whole group.
    """
    override = _advanced_label(label, settings, "sampleLabels", sample)
    if override != label:
        return override
    renamed = _advanced_label(str(condition), settings, "conditionLabels")
    if renamed == str(condition):
        return label
    # Rebuild rather than string-replace: a condition whose name occurs inside
    # the replicate suffix would otherwise be substituted twice.
    return str(label).replace(str(condition), renamed, 1)


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
    """Font, colour, frame and title of a legend that already exists.

    Hiding one is handled by the caller, because a legend is removed rather than
    restyled -- see `_apply_legend_visibility`.
    """
    if legend is None:
        return
    size = _advanced_number(settings, "legendFontSize", 0.0)
    colour = _advanced_color_text(settings, "legendTextColor")
    family = mpl_font_family(settings, "legend")
    for text in legend.get_texts():
        if size > 0:
            text.set_fontsize(size)
        if colour:
            text.set_color(colour)
        _set_font_family(text, family)

    title_text = _advanced_text(settings, "legendTitle")
    if title_text is not None:
        legend.set_title(title_text)
    title = legend.get_title()
    if title is not None:
        if size > 0:
            title.set_fontsize(size)
        if colour:
            title.set_color(colour)
        _set_font_family(title, family)

    # A frame is drawn by default on matplotlib and not by every plot here, so
    # the setting is tri-state: absent leaves whatever the plot chose.
    frame = _advanced_optional_bool(settings, "legendFrame")
    if frame is not None:
        legend.set_frame_on(frame)


def _advanced_optional_bool(settings: dict[str, Any] | None, key: str) -> bool | None:
    """A boolean that can also be absent, so a plot's own choice survives."""
    if not settings or key not in settings:
        return None
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _apply_legend_visibility(ax, settings: dict[str, Any] | None) -> None:
    """Remove a legend the user has switched off.

    Every plot decides for itself whether to build one, so this only ever takes
    one away -- there is nothing to put back if the plot drew no handles.
    """
    if _advanced_optional_bool(settings, "legendVisible") is False:
        legend = ax.get_legend()
        if legend is not None:
            legend.remove()


_GRID_PLACEMENT_KEYS = ("gridLineVisible", "gridLineAxis")
_FRAME_SIDE_KEYS = {
    "top": "axisLineTop",
    "right": "axisLineRight",
    "bottom": "axisLineBottom",
    "left": "axisLineLeft",
}


def _mpl_grid_is_on(axis) -> bool:
    """Whether an axis currently draws grid lines, before anything is drawn."""
    flag = getattr(axis, "_major_tick_kw", {}).get("gridOn")
    if flag is not None:
        return bool(flag)
    return any(line.get_visible() for line in axis.get_gridlines())


def _apply_mpl_grid_settings(
    ax, settings: dict[str, Any], *, theme_grid_color: str | None = None
) -> None:
    """Apply the grid settings that are present, and only those.

    Placement -- whether there is a grid and on which axes -- is one decision
    and arrives as a pair from the panel. Colour, width and style are three
    more, each on its own. The old code rebuilt the whole grid whenever any one
    of the five was present, filling the other four with its own defaults, so a
    colour change on a gridless plot switched a y grid on, and a colour change
    on a plot with an x grid moved it to y.
    """
    present = {key for key in (*_GRID_PLACEMENT_KEYS, "gridLineColor", "gridLineWidth", "gridLineStyle") if key in settings}
    if not present:
        return
    x_on, y_on = _mpl_grid_is_on(ax.xaxis), _mpl_grid_is_on(ax.yaxis)
    was_on = {"x": x_on, "y": y_on}
    if present & set(_GRID_PLACEMENT_KEYS):
        visible = _advanced_bool(settings, "gridLineVisible", True)
        where = _advanced_choice(settings, "gridLineAxis", {"x", "y", "both"}, "y")
        x_on = visible and where in {"x", "both"}
        y_on = visible and where in {"y", "both"}

    style: dict[str, Any] = {}
    if "gridLineColor" in present:
        colour = _advanced_color_text(settings, "gridLineColor")
        if colour:
            style["color"] = colour
    if "gridLineWidth" in present:
        style["linewidth"] = max(0.0, _advanced_number(settings, "gridLineWidth", 0.8))
    if "gridLineStyle" in present:
        style["linestyle"] = _mpl_grid_line_style(settings)

    for name, on in (("x", x_on), ("y", y_on)):
        if not on:
            if was_on[name]:
                ax.grid(False, axis=name)
            continue
        kwargs = dict(style)
        # A grid this edit switches on has no native look to keep. It is drawn
        # as the panel shows it, for whatever the edit did not name.
        if not was_on[name]:
            kwargs.setdefault("color", theme_grid_color or "#d1d5db")
            kwargs.setdefault("linewidth", 0.8)
            kwargs.setdefault("linestyle", _mpl_grid_line_style(settings))
        ax.grid(True, axis=name, **kwargs)


def _apply_mpl_frame_settings(
    ax, settings: dict[str, Any], *, theme_axis_color: str | None = None
) -> None:
    """Apply the frame settings that are present, and only those.

    Which sides are drawn is one decision and arrives from the panel as all
    four sides together; colour, width and style are each their own. A theme
    that names an axis colour recolours the frame as a whole, because choosing a
    theme is asking for a whole look.
    """
    if "axisLineVisible" in settings and not _advanced_bool(settings, "axisLineVisible", True):
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="both", length=0)
        return

    for name, spine in ax.spines.items():
        key = _FRAME_SIDE_KEYS.get(name)
        if key and key in settings:
            spine.set_visible(_advanced_bool(settings, key, True))

    colour = _advanced_color_text(settings, "axisLineColor") if "axisLineColor" in settings else None
    colour = colour or theme_axis_color
    width = (
        max(0.0, _advanced_number(settings, "axisLineWidth", 1.0))
        if "axisLineWidth" in settings
        else None
    )
    line_style = _mpl_axis_line_style(settings) if "axisLineStyle" in settings else None
    for spine in ax.spines.values():
        if not spine.get_visible():
            continue
        if colour:
            spine.set_color(colour)
        if width is not None:
            spine.set_linewidth(width)
        if line_style is not None:
            spine.set_linestyle(line_style)
    if colour:
        ax.tick_params(axis="both", color=colour)


def _apply_plotly_grid_settings(layout: dict[str, Any], settings: dict[str, Any]) -> None:
    """The grid settings that are present, written into a Plotly layout.

    Placement is a pair (visible, axis); colour, width and dash are each their
    own. Nothing absent is written, so the template's grid -- white on the
    default template, pale grey on `plotly_white` -- survives an edit that did
    not name it.
    """
    axes = ("xaxis", "yaxis")
    scene = ("xaxis", "yaxis", "zaxis")
    if any(key in settings for key in _GRID_PLACEMENT_KEYS):
        visible = _advanced_bool(settings, "gridLineVisible", True)
        where = _advanced_choice(settings, "gridLineAxis", {"x", "y", "both"}, "y")
        shown = {"xaxis": visible and where in {"x", "both"}, "yaxis": visible and where in {"y", "both"}}
        for axis_key in axes:
            layout.setdefault(axis_key, {})["showgrid"] = shown[axis_key]
        for axis_key in scene:
            layout.setdefault("scene", {}).setdefault(axis_key, {})["showgrid"] = visible
    props: dict[str, Any] = {}
    if "gridLineColor" in settings:
        colour = _advanced_color_text(settings, "gridLineColor")
        if colour:
            props["gridcolor"] = colour
    if "gridLineWidth" in settings:
        props["gridwidth"] = max(0.0, _advanced_number(settings, "gridLineWidth", 0.8))
    if "gridLineStyle" in settings:
        props["griddash"] = _plotly_grid_line_style(settings)
    if props:
        for axis_key in axes:
            layout.setdefault(axis_key, {}).update(props)
        scene_props = {k: v for k, v in props.items() if k != "griddash"}
        for axis_key in scene:
            layout.setdefault("scene", {}).setdefault(axis_key, {}).update(scene_props)


def _apply_plotly_frame_settings(layout: dict[str, Any], settings: dict[str, Any]) -> None:
    """The frame settings that are present, written into a Plotly layout.

    Plotly has no per-side line: an axis line is on or off, and `mirror`
    repeats it on the opposite side. The four sides therefore arrive together
    and are reduced to that. Tick marks come with a drawn frame and go with it,
    which is the only property set here that the settings do not name.
    """
    sides_named = "axisLineVisible" in settings or any(key in settings for key in _FRAME_SIDE_KEYS.values())
    if sides_named:
        visible = _advanced_bool(settings, "axisLineVisible", True)
        sides = _advanced_axis_sides(settings)
        x_visible = visible and (sides["bottom"] or sides["top"])
        y_visible = visible and (sides["left"] or sides["right"])
        xaxis = layout.setdefault("xaxis", {})
        xaxis["showline"] = x_visible
        xaxis["ticks"] = "outside" if x_visible else ""
        if sides["top"] and not sides["bottom"]:
            xaxis["side"] = "top"
        xaxis["mirror"] = bool(sides["top"] and sides["bottom"])
        yaxis = layout.setdefault("yaxis", {})
        yaxis["showline"] = y_visible
        yaxis["ticks"] = "outside" if y_visible else ""
        if sides["right"] and not sides["left"]:
            yaxis["side"] = "right"
        yaxis["mirror"] = bool(sides["right"] and sides["left"])
        for axis_key in ("xaxis", "yaxis", "zaxis"):
            layout.setdefault("scene", {}).setdefault(axis_key, {})["showline"] = visible and any(sides.values())
    props: dict[str, Any] = {}
    if "axisLineColor" in settings:
        colour = _advanced_color_text(settings, "axisLineColor")
        if colour:
            props["linecolor"] = colour
            props["tickcolor"] = colour
    if "axisLineWidth" in settings:
        props["linewidth"] = max(0.0, _advanced_number(settings, "axisLineWidth", 1.0))
    if props:
        for axis_key in ("xaxis", "yaxis"):
            layout.setdefault(axis_key, {}).update(props)
        for axis_key in ("xaxis", "yaxis", "zaxis"):
            layout.setdefault("scene", {}).setdefault(axis_key, {}).update(props)


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

    # A setting changes what it names and nothing else. Recolouring the grid
    # does not switch it on; hiding the top of the frame does not recolour the
    # other three sides. Anything the settings do not name stays exactly as the
    # plot drew it, which is what makes an untouched panel the native figure.
    _apply_mpl_grid_settings(ax, settings, theme_grid_color=grid_color)
    _apply_mpl_frame_settings(ax, settings, theme_axis_color=axis_color)


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
    # "Show title" lives here rather than as a per-plot `header` parameter, so
    # one switch covers every plot instead of twenty checkboxes that each had to
    # be wired through their own route.
    if _advanced_optional_bool(settings, "titleVisible") is False:
        ax.set_title("")
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
    if "color" in title_props:
        title_obj.set_color(title_props["color"])
    if "color" in x_props:
        ax.xaxis.label.set_color(x_props["color"])
    if "color" in y_props:
        ax.yaxis.label.set_color(y_props["color"])
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
    x_tick_color = _advanced_color_text(settings, "xTickLabelColor")
    y_tick_color = _advanced_color_text(settings, "yTickLabelColor")
    if x_tick_color:
        ax.tick_params(axis="x", colors=x_tick_color)
        # `colors` paints the tick marks as well, so the spine is restored to
        # whatever the frame settings asked for rather than following the text.
        ax.xaxis.label.set_color(x_props.get("color", ax.xaxis.label.get_color()))
    if y_tick_color:
        ax.tick_params(axis="y", colors=y_tick_color)
        ax.yaxis.label.set_color(y_props.get("color", ax.yaxis.label.get_color()))
    if x_tick_rotation is not None:
        for label in ax.get_xticklabels():
            label.set_rotation(x_tick_rotation)
    if y_tick_rotation is not None:
        for label in ax.get_yticklabels():
            label.set_rotation(y_tick_rotation)

    # The face, last, so it reaches artists the lines above may have replaced.
    # `ax.texts` is every annotation the plot drew -- the numbers on bars and
    # boxes, the r and N box on a correlation, the labels beside volcano hits --
    # which is what makes "every text in the plot" true rather than nearly true.
    _set_font_family(title_obj, mpl_font_family(settings, "title"))
    _set_font_family(ax.xaxis.label, mpl_font_family(settings, "axisLabel"))
    _set_font_family(ax.yaxis.label, mpl_font_family(settings, "axisLabel"))
    tick_family = mpl_font_family(settings, "tick")
    if tick_family is not None:
        for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
            _set_font_family(label, tick_family)
    annotation_family = mpl_font_family(settings, "valueLabel")
    if annotation_family is not None:
        for text in ax.texts:
            _set_font_family(text, annotation_family)

    _apply_legend_visibility(ax, settings)
    _style_legend(ax.get_legend(), settings)



def fitted_group_ellipse(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Fit an enclosing ellipse only when the group reliably spans the plane."""
    array = np.asarray(points, dtype=float)
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


def ellipse_skip_message(groups: Sequence[str]) -> str:
    """What to say under the plot about the groups that got no ellipse."""
    names = [str(group) for group in groups if str(group).strip()]
    if not names:
        return ""
    listed = ", ".join(names)
    subject = "group" if len(names) == 1 else "groups"
    return (
        f"No ellipse was drawn for {subject} {listed}: {'its' if len(names) == 1 else 'their'} "
        "points have no spread in one direction -- they fall on a line, or two "
        "samples share the same position -- so there is no enclosing ellipse to fit. "
        "The points themselves are unaffected."
    )


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

    # The same element colours the static renderer applies, so one setting means
    # one thing whichever renderer is on screen.
    title_props = _advanced_element_font_props(settings, "titleElement")
    x_props = _advanced_element_font_props(settings, "xLabelElement")
    y_props = _advanced_element_font_props(settings, "yLabelElement")
    if "color" in title_props:
        layout.setdefault("title_font", {})["color"] = title_props["color"]
    for axis_key, props in (("xaxis", x_props), ("yaxis", y_props)):
        if "color" in props:
            layout.setdefault(axis_key, {}).setdefault("title", {}).setdefault("font", {})[
                "color"
            ] = props["color"]
    for axis_key, colour_key in (("xaxis", "xTickLabelColor"), ("yaxis", "yTickLabelColor")):
        tick_colour = _advanced_color_text(settings, colour_key)
        if tick_colour:
            layout.setdefault(axis_key, {}).setdefault("tickfont", {})["color"] = tick_colour

    if _advanced_optional_bool(settings, "titleVisible") is False:
        layout["title"] = ""
    if _advanced_optional_bool(settings, "legendVisible") is False:
        layout["showlegend"] = False
    legend_title = _advanced_text(settings, "legendTitle")
    if legend_title is not None:
        layout.setdefault("legend", {}).setdefault("title", {})["text"] = legend_title
    legend_colour = _advanced_color_text(settings, "legendTextColor")
    if legend_colour:
        layout.setdefault("legend", {}).setdefault("font", {})["color"] = legend_colour
    legend_frame = _advanced_optional_bool(settings, "legendFrame")
    if legend_frame is not None:
        legend = layout.setdefault("legend", {})
        # Plotly has no frame switch: a frame is a border width and a
        # background, so turning it off is width 0 and a transparent fill.
        legend["borderwidth"] = 1 if legend_frame else 0
        if not legend_frame:
            legend["bgcolor"] = "rgba(0,0,0,0)"

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
    # Only what the settings name. The grid colour does not switch the grid on,
    # a side of the frame does not recolour the others -- see the matplotlib
    # counterparts, which follow the same rule for the same reason.
    _apply_plotly_grid_settings(layout, settings)
    _apply_plotly_frame_settings(layout, settings)
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
        # `setdefault`, not assignment: this line used to replace the whole font
        # dict and so quietly dropped the legend text colour set above it
        # whenever a size was given as well.
        layout.setdefault("legend", {}).setdefault("font", {})["size"] = legend_size
    # Bold and italic used to be faked by swapping the family to "Arial Black"
    # or "Arial Italic", which meant asking for a bold title silently changed its
    # typeface -- and would have overwritten any face chosen below. Plotly has
    # carried real `weight` and `style` since 5.23, so they are set as
    # themselves and the family is left to say what face it is.
    for element_key, target in (
        ("titleElement", lambda: layout.setdefault("title_font", {})),
        ("xLabelElement", lambda: layout.setdefault("xaxis", {}).setdefault("title", {}).setdefault("font", {})),
        ("yLabelElement", lambda: layout.setdefault("yaxis", {}).setdefault("title", {}).setdefault("font", {})),
    ):
        element = _advanced_element(settings, element_key)
        if element.get("bold"):
            target()["weight"] = "bold"
        if element.get("italic"):
            target()["style"] = "italic"

    # The face. The global one goes on `layout.font`, which every text in the
    # figure inherits -- including the hover labels and the annotations a plot
    # drew itself -- and the four elements that may disagree override it.
    global_family = plotly_font_family(settings)
    if global_family:
        font["family"] = global_family
    title_family = plotly_font_family(settings, "title")
    if title_family:
        layout.setdefault("title_font", {})["family"] = title_family
    axis_family = plotly_font_family(settings, "axisLabel")
    if axis_family:
        for axis_key in ("xaxis", "yaxis"):
            layout.setdefault(axis_key, {}).setdefault("title", {}).setdefault("font", {})[
                "family"
            ] = axis_family
    tick_family = plotly_font_family(settings, "tick")
    if tick_family:
        for axis_key in ("xaxis", "yaxis"):
            layout.setdefault(axis_key, {}).setdefault("tickfont", {})["family"] = tick_family
    legend_family = plotly_font_family(settings, "legend")
    if legend_family:
        layout.setdefault("legend", {}).setdefault("font", {})["family"] = legend_family

    if font:
        layout["font"] = font
    legend_x = _advanced_number(settings, "legendXOffset", 0.0)
    legend_y = _advanced_number(settings, "legendYOffset", 0.0)
    if legend_x or legend_y:
        layout.setdefault("legend", {})["x"] = 1.02 + _plotly_pixel_fraction(legend_x, width_px)
        layout.setdefault("legend", {})["y"] = 1.0 + _plotly_pixel_fraction(legend_y, height_px)
    return layout


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
    ax.set_xlabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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
    ax.set_xlabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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
    method_label = "Numerical" if str(method).strip().lower() == "numerical" else "Quantile"
    ax.set_title(f"Distribution of data after {method_label.lower()} imputation")
    ax.set_xlabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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


def distribution_qqnorm_plot(
    kind: AnnotationKind,
    random_seed: int = 187,
    advanced: dict[str, Any] | None = None,
) -> bytes:
    plt = _get_plt()
    frame = _distribution_frame(kind)
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

    fig, ax = plt.subplots()
    ax.scatter(x, y, **marker_style(advanced, size=2.5, alpha=0.5, color_default="black"))
    line = resolve_reference_line(advanced, color="red", style="solid", width=2.0)
    if len(fit_line) >= 2 and line.visible:
        fx = [fit_line[0][0], fit_line[1][0]]
        fy = [fit_line[0][1], fit_line[1][1]]
        ax.plot(fx, fy, **line.matplotlib())
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
    frame = _coverage_frame(kind)
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
            for bar in bars:
                height = float(bar.get_height())
                x_pos, y_pos = _advanced_text_position(advanced, bar.get_x() + bar.get_width() / 2, height * 0.02)
                ax.text(
                    x_pos,
                    y_pos,
                    f"{int(np.ceil(height))}",
                    ha="center",
                    va="bottom",
                    fontsize=advanced_label_size(advanced, text_size),
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
                        fontsize=advanced_label_size(advanced, text_size),
                        fontweight="bold",
                        color="black",
                        rotation=90,
                    )
        ax.set_xticks(positions)
        ax.set_xticklabels(
            [
                _rename_composite_sample_label(label, sample, condition, advanced)
                for label, sample, condition in zip(
                    meta["label"].tolist(),
                    meta["sample"].astype(str).tolist(),
                    meta["condition"].astype(str).tolist(),
                )
            ],
            rotation=90,
            fontsize=6,
        )
        ax.set_xlabel("Condition")
        ymax = float(meta["count"].max()) if not meta.empty else 0.0

    if red_line_value is not None and reference_line:
        line = resolve_reference_line(advanced, color="red")
        if line.visible:
            ax.axhline(y=red_line_value, **line.matplotlib())
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

    # 10 % headroom above whatever is tallest: the total line when it is drawn,
    # otherwise the tallest bar. With the line off the axis is measured from
    # the bars, not from a line that is not there.
    headroom = 1.1
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

    ax.set_xlabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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


def _peptide_coverage_summary(include_id=False, quantity_column=None, level="peptide"):
    from app.services.peptide_tools import (
        _sample_rename_map,
        get_peptide_frame,
    )

    if level not in {"peptide", "precursor"}:
        raise ValueError("Coverage level must be peptide or precursor.")
    frame = get_peptide_frame()
    file_col = _peptide_file_column(frame)
    if level == "precursor":
        from app.services.completeness_tools import _peptide_precursor_column

        seq_col = _peptide_precursor_column(frame)
    else:
        seq_col = _peptide_sequence_column(frame)
    quantity_col = _peptide_quantity_column(frame, requested=quantity_column)
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
    summary = data_filtered.notna().sum(axis=0).reset_index()
    summary.columns = ["Sample", "Value"]
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=selected, ordered=True)
    summary = summary.sort_values("Sample")
    peptides_count = int(pivot.shape[0])

    return summary, peptides_count, meta


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
    color_map = _advanced_condition_colors("protein", plt, ordered_conditions, advanced)
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
                    fontsize=advanced_label_size(advanced, text_size),
                    rotation=0,
                    color="black",
                    fontweight="bold",
                )

        ax.set_xticks(range(1, len(samples) + 1))
        ax.set_xticklabels(
            [
                _rename_composite_sample_label(sample, raw_sample, condition, advanced)
                for sample, raw_sample, condition in zip(
                    samples,
                    meta["sample"].astype(str).tolist(),
                    meta["condition"].astype(str).tolist(),
                )
            ],
            rotation=90,
            ha="center",
        )
        ax.set_ylabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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
                    fontsize=advanced_label_size(advanced, text_size),
                    color="black",
                    rotation=0,
                    fontweight="bold",
                )

        ax.set_xticks(positions)
        ax.set_xticklabels([_advanced_label(condition, advanced, "conditionLabels") for condition in valid_conditions])
        ax.set_xlabel("Condition")
        ax.set_ylabel(intensity_unit_label(_phosprot_values_are_centred(kind)))
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
    frame = _original_scale_frame(kind)
    sample_columns = _get_sample_columns(kind, frame)
    if not sample_columns:
        raise ValueError(f"No sample columns found for {kind} dataset.")

    meta = _metadata_for_kind(kind, frame, sample_columns)
    numeric = raw_zero_to_nan(frame, sample_columns)[sample_columns]
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
            ax.text(x_pos, y_pos, f"{med:.2f}", ha="center", va="bottom", fontsize=advanced_label_size(advanced, text_size), fontweight="bold", color="black")

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
    dbscan_eps: float = 0.5,
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
    return {
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
                dbscan_eps=dbscan_eps,
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
    x_std = x_centered.std(axis=0, keepdims=True)
    x_std[x_std == 0] = 1.0
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


def _compute_cluster_labels(
    embedding: np.ndarray,
    *,
    cluster_method: str = "None",
    cluster_count: int = 3,
    dbscan_eps: float = 0.5,
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
    dbscan_eps: float,
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
            dbscan_eps=dbscan_eps,
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
    dbscan_eps: float = 0.5,
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
                **marker_style(
                    advanced,
                    size=_pca_default_size(dot_size),
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
                **marker_style(
                    advanced,
                    size=_pca_default_size(dot_size),
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
    dbscan_eps: float = 0.5,
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
        apply_plotly_group_markers(
            fig,
            advanced,
            size=_pca_default_size(dot_size),
            alpha=0.85,
            display_to_group={
                _advanced_label(group, advanced, "conditionLabels"): group
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
    apply_plotly_group_markers(
        fig,
        advanced,
        size=_pca_default_size(dot_size),
        alpha=0.85,
        display_to_group={
            _advanced_label(group, advanced, "conditionLabels"): group for group in groups
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
    fig.update_layout(**_advanced_plotly_layout(advanced, width_px=_cm_to_px(width_cm), height_px=height_px))

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
    frame = _original_scale_frame(kind)
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
            label=_advanced_label(condition, advanced, "conditionLabels"),
            **marker_style(
                advanced,
                size=2.7,
                alpha=1.0,
                group=condition,
                color=color_map[condition],
            ),
        )

    ax.set_xlabel(f"{workflow} Rank")
    ax.set_ylabel(abundance_axis_label(workflow, _phosprot_values_are_centred(kind)))
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
    apply_plotly_group_markers(
        fig,
        advanced,
        size=6,
        alpha=0.85,
        display_to_group={
            _advanced_label(condition, advanced, "conditionLabels"): condition
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
        yaxis_title=abundance_axis_label(workflow, _phosprot_values_are_centred(kind)),
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
    frame = _log2_qc_frame(kind)
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
    # has to be applied to it as well; see _rename_composite_sample_label.
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
    cmap = plt.get_cmap(cmap_name).copy()
    cmap.set_bad("#eeeeee")
    color_norm = plt.Normalize(vmin=vmin, vmax=vmax)
    method_normalized = str(method).strip().lower()
    x_labels = [
        _rename_composite_sample_label(
            str(label),
            original_by_label.get(str(label), ""),
            condition_by_label.get(str(label), ""),
            advanced,
        )
        for label in ordered_corr.columns.tolist()
    ]
    y_labels = [
        _rename_composite_sample_label(
            str(label),
            original_by_label.get(str(label), ""),
            condition_by_label.get(str(label), ""),
            advanced,
        )
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
                if not np.isfinite(r):
                    continue
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

    missing_rows, missing_cols = np.where(~np.isfinite(ordered_corr.to_numpy()))
    offset = 0.5 if method_normalized == "ellipse" else 0
    for i, j in zip(missing_rows, missing_cols):
        ax.text(j + offset, i + offset, "NA", ha="center", va="center", fontsize=7, color="#666666")
    ax.set_xlabel("Samples" + ("\nNA: correlation unavailable; clustering skipped (metadata order)" if incomplete else ""))
    ax.set_ylabel("Samples")
    _apply_advanced_axes(ax, advanced)
    plt.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)

from __future__ import annotations
"""Advanced plot settings: reading them, and applying them to a figure.

Every renderer in the application draws through this module. The panel sends a
JSON object of only what the user changed; these helpers read a value out of it,
resolve markers, fonts, colours, grids, frames and reference lines, and write
the result into a matplotlib axes (`apply_advanced_axes`) or a plotly layout
(`advanced_plotly_layout`).

It lived inside `plot_images.py` until now, which made the QC renderer module a
dependency of every other renderer module: seven of them imported its private
names. The engine is not QC-specific, so it is its own module and the names the
other modules need are public.
"""

import json
import math
import re
from functools import lru_cache
from dataclasses import dataclass
from typing import Any


from app.schemas.annotation import AnnotationKind
from app.services.condition_palette_store import build_condition_color_map
# <plot-vocabulary> the panel's vocabularies; notebook exports inline them here
from app.services.plot_vocabulary import LINE_STYLE_NAMES, MARKER_SHAPES, PLOT_FONTS, PLOT_THEME_MAP
# </plot-vocabulary>
from app.services.plotting_common import get_plt as _get_plt

def _condition_colors(kind: AnnotationKind, _plt, conditions: list[str]) -> dict[str, str]:
    # build_condition_color_map trims and de-duplicates the names itself.
    return build_condition_color_map(kind, conditions)


def parse_advanced_plot_settings(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return migrate_advanced_plot_settings(parsed)


# Keys an older version of the panel wrote and no control writes any more.
FRAME_SWITCH_KEY = "axisLineVisible"
RETIRED_TEXT_OFFSET_KEYS = ("textXOffset", "textYOffset")


def migrate_advanced_plot_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings saved by an older panel, in the keys the current one writes.

    The single frame switch became four per-side boxes: an old "frame off" is
    all four sides off, unless a side was already set on its own. The value
    label offsets had no control since the panel was redesigned and are
    dropped. The frontend migrates the same way when it restores a session
    (`migrateAdvancedPlotSettings` in frontend/src/lib/plotSerialization.ts),
    so the panel shows what the plot draws.
    """
    if not isinstance(settings, dict) or not (
        FRAME_SWITCH_KEY in settings or any(key in settings for key in RETIRED_TEXT_OFFSET_KEYS)
    ):
        return settings
    migrated = {key: value for key, value in settings.items()
                if key != FRAME_SWITCH_KEY and key not in RETIRED_TEXT_OFFSET_KEYS}
    frame = settings.get(FRAME_SWITCH_KEY)
    if isinstance(frame, bool):
        for key in ("axisLineTop", "axisLineRight", "axisLineBottom", "axisLineLeft"):
            migrated.setdefault(key, frame)
    return migrated


def advanced_text(settings: dict[str, Any] | None, key: str) -> str | None:
    value = (settings or {}).get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def advanced_number(settings: dict[str, Any] | None, key: str, default: float = 0.0) -> float:
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
    return advanced_color_text(settings, key) or default


def advanced_label_size(settings: dict[str, Any] | None, default: float) -> float:
    """The size of the value labels drawn on bars and boxes.

    Was a per-page "Text Size" field, clamped 6-20 on one page, 6-24 on another
    and unbounded on a third. One setting, one floor.
    """
    return max(4.0, advanced_number(settings, "valueLabelSize", default))


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


def advanced_size(settings: dict[str, Any] | None, key: str, default: float) -> float:
    """A marker diameter from the advanced settings, floored at something visible."""
    return max(0.5, advanced_number(settings, key, default))


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


def group_override(
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
    name = advanced_text(settings, "correlationColorMap")
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
    size_override = group_override(settings, "conditionMarkerSizes", group)
    diameter = (
        max(0.5, float(size_override))
        if size_override is not None
        else advanced_size(settings, size_key, size)
    )

    alpha_override = group_override(settings, "conditionMarkerAlphas", group)
    opacity = (
        min(1.0, max(0.0, float(alpha_override)))
        if alpha_override is not None
        else advanced_alpha(settings, alpha_key, alpha)
    )

    edge_width = group_override(settings, "conditionMarkerEdgeWidths", group)
    if edge_width is None:
        edge_width = advanced_number(settings, edge_width_key, edge_width_default)
    edge_width = max(0.0, float(edge_width))

    edge_color = group_override(settings, "conditionMarkerEdgeColors", group)
    if edge_color is None:
        edge_color = advanced_text(settings, edge_color_key)

    shape = group_override(settings, "conditionMarkerShapes", group)
    if shape is None:
        shape = advanced_text(settings, "markerShape")

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


def pca_default_size(dot_size: float) -> float:
    """The old `dotSize` number, read as a diameter.

    The projection's legacy control multiplied its value by 10 for matplotlib
    and passed it raw to plotly, so the two renderers drew different dots from
    one setting. The number now means a diameter in both, and the historical
    default of 5 lands on a dot of about the size it used to draw.
    """
    return max(1.0, float(dot_size)) * 1.2


def advanced_alpha(settings: dict[str, Any] | None, key: str, default: float) -> float:
    """An opacity from the advanced settings, clamped to the range that exists."""
    return min(1.0, max(0.0, advanced_number(settings, key, default)))


def advanced_optional_number(settings: dict[str, Any] | None, key: str) -> float | None:
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
    value = advanced_text(settings, key)
    if value in allowed:
        return value
    return default


def advanced_color_text(settings: dict[str, Any] | None, key: str) -> str | None:
    value = advanced_text(settings, key)
    if not value:
        return None
    return value


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #


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
        name = advanced_text(settings, key)
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


def _advanced_theme(settings: dict[str, Any] | None) -> dict[str, str]:
    theme_id = _advanced_choice(settings, "plotTheme", set(PLOT_THEME_MAP), "default")
    return PLOT_THEME_MAP.get(theme_id, {})


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
    # Whether a plot that names its line in the legend does so; the line itself
    # is unaffected (coverage total, 2026-10-09).
    legend_entry: bool = True

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
        color=advanced_color_text(settings, "referenceLineColor") or color,
        style=_advanced_choice(settings, "referenceLineStyle", LINE_STYLE_NAMES, style),
        width=max(0.0, advanced_number(settings, "referenceLineWidth", width)),
        legend_entry=_advanced_bool(settings, "referenceLineLegend", True),
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


def advanced_element_text(settings: dict[str, Any] | None, element_key: str) -> str | None:
    text = _advanced_element(settings, element_key).get("text")
    clean = str(text).strip() if text is not None else ""
    return clean or None


def advanced_element_number(
    settings: dict[str, Any] | None,
    element_key: str,
    element_number_key: str,
) -> float:
    value = _advanced_element(settings, element_key).get(element_number_key)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
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


def advanced_label(value: str, settings: dict[str, Any] | None, key: str, *aliases: object) -> str:
    labels = _advanced_map(settings, key)
    value_text = str(value)
    return _advanced_map_lookup(labels, value_text, *aliases) or value_text


def _advanced_color(value: str, default: str, settings: dict[str, Any] | None) -> str:
    colors = _advanced_map(settings, "conditionColors")
    value_text = str(value)
    display_text = advanced_label(value_text, settings, "conditionLabels")
    return _advanced_map_lookup(colors, value_text, display_text) or default


def rename_composite_sample_label(
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
    override = advanced_label(label, settings, "sampleLabels", sample)
    if override != label:
        return override
    renamed = advanced_label(str(condition), settings, "conditionLabels")
    if renamed == str(condition):
        return label
    # Rebuild rather than string-replace: a condition whose name occurs inside
    # the replicate suffix would otherwise be substituted twice.
    return str(label).replace(str(condition), renamed, 1)


def advanced_condition_colors(
    kind: AnnotationKind,
    plt,
    conditions: list[str],
    settings: dict[str, Any] | None,
) -> dict[str, str]:
    base = _condition_colors(kind, plt, conditions)
    return {condition: _advanced_color(condition, color, settings) for condition, color in base.items()}


def _offset_text(artist, fig, x_px: float, y_px: float) -> None:
    """Move a title or axis label by a number of figure pixels from where it sits.

    The offset is added to the text's own transform, so matplotlib still places
    the label (an axis label stays clear of its tick labels) and the layout
    still measures it. Setting coordinates instead mixed two systems: a label's
    automatic position is partly in display pixels, and `set_label_coords`
    read it as axes fractions, so a 2 px nudge put the label tens of axes-widths
    away and the export refused the figure as not fitting.

    Pixels are taken at the figure's dpi, as everywhere else in this module, and
    scale with it when the figure is saved at another. Applying it again
    replaces the earlier offset rather than adding to it.
    """
    from matplotlib.transforms import ScaledTranslation

    base = getattr(artist, "_copylot_base_transform", None)
    if base is None:
        if not (x_px or y_px):
            return
        base = artist.get_transform()
        artist._copylot_base_transform = base
    dpi = float(getattr(fig, "dpi", 100.0)) or 100.0
    artist.set_transform(base + ScaledTranslation(x_px / dpi, y_px / dpi, fig.dpi_scale_trans))
    axes = getattr(artist, "axes", None)
    if axes is not None and artist is getattr(axes, "title", None) and y_px:
        # Left on, matplotlib lifts a title it finds overlapping the axes back
        # above them, undoing a nudge downwards. `set_title(y=...)` turns it
        # off the same way.
        axes._autotitlepos = False


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


# The gap Plotly leaves between a title and the top of the plot area.
PLOTLY_TITLE_GAP_PX = 20


def _plotly_title_offset(offset_px: float, height_px: int) -> dict[str, Any]:
    """A title moved up or down by `offset_px` pixels, in Plotly's terms.

    Plotly accepts a title position only between 0 and 1, and the default
    already sits at the top of the figure, so the old `1 + offset` refused every
    plot whose title was raised by any amount. The title is instead anchored to
    the top of the plot area with a gap in pixels: raising it widens the gap,
    and `automargin` grows the figure's top margin so a raised title stays on
    the canvas. Lowering it past the default gap moves it into the plot area.
    """
    gap = PLOTLY_TITLE_GAP_PX + float(offset_px)
    layout: dict[str, Any] = {
        "title_yref": "paper",
        "title_yanchor": "bottom",
        "title_automargin": True,
    }
    if gap >= 0:
        layout["title_y"] = 1.0
        layout["title_pad"] = {"b": gap}
    else:
        layout["title_y"] = max(0.0, 1.0 + _plotly_pixel_fraction(gap, height_px))
        layout["title_pad"] = {"b": 0}
    return layout


def advanced_anchor(ax, settings: dict[str, Any] | None, x: float, y: float) -> tuple[float, float]:
    return (
        x + _fig_pixel_fraction(ax.figure, advanced_number(settings, "legendXOffset", 0.0), "x"),
        y + _fig_pixel_fraction(ax.figure, advanced_number(settings, "legendYOffset", 0.0), "y"),
    )


def _style_legend(legend, settings: dict[str, Any] | None) -> None:
    """Font, colour, frame and title of a legend that already exists.

    Hiding one is handled by the caller, because a legend is removed rather than
    restyled -- see `_apply_legend_visibility`.
    """
    if legend is None:
        return
    size = advanced_number(settings, "legendFontSize", 0.0)
    colour = advanced_color_text(settings, "legendTextColor")
    family = mpl_font_family(settings, "legend")
    for text in legend.get_texts():
        if size > 0:
            text.set_fontsize(size)
        if colour:
            text.set_color(colour)
        _set_font_family(text, family)

    title_text = advanced_text(settings, "legendTitle")
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
        colour = advanced_color_text(settings, "gridLineColor")
        if colour:
            style["color"] = colour
    if "gridLineWidth" in present:
        style["linewidth"] = max(0.0, advanced_number(settings, "gridLineWidth", 0.8))
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
    for name, spine in ax.spines.items():
        key = _FRAME_SIDE_KEYS.get(name)
        if key and key in settings:
            spine.set_visible(_advanced_bool(settings, key, True))

    colour = advanced_color_text(settings, "axisLineColor") if "axisLineColor" in settings else None
    colour = colour or theme_axis_color
    width = (
        max(0.0, advanced_number(settings, "axisLineWidth", 1.0))
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
        colour = advanced_color_text(settings, "gridLineColor")
        if colour:
            props["gridcolor"] = colour
    if "gridLineWidth" in settings:
        props["gridwidth"] = max(0.0, advanced_number(settings, "gridLineWidth", 0.8))
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
    sides_named = any(key in settings for key in _FRAME_SIDE_KEYS.values())
    if sides_named:
        sides = _advanced_axis_sides(settings)
        x_visible = sides["bottom"] or sides["top"]
        y_visible = sides["left"] or sides["right"]
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
            layout.setdefault("scene", {}).setdefault(axis_key, {})["showline"] = any(sides.values())
    props: dict[str, Any] = {}
    if "axisLineColor" in settings:
        colour = advanced_color_text(settings, "axisLineColor")
        if colour:
            props["linecolor"] = colour
            props["tickcolor"] = colour
    if "axisLineWidth" in settings:
        props["linewidth"] = max(0.0, advanced_number(settings, "axisLineWidth", 1.0))
    if props:
        for axis_key in ("xaxis", "yaxis"):
            layout.setdefault(axis_key, {}).update(props)
        for axis_key in ("xaxis", "yaxis", "zaxis"):
            layout.setdefault("scene", {}).setdefault(axis_key, {}).update(props)


def apply_advanced_matplotlib_style(ax, settings: dict[str, Any] | None) -> None:
    if not settings:
        return
    fig = ax.figure
    theme = _advanced_theme(settings)
    text_color = theme.get("text")
    axis_color = theme.get("axis")
    grid_color = theme.get("grid")
    background = advanced_color_text(settings, "backgroundColor")
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


def apply_advanced_axes(ax, settings: dict[str, Any] | None) -> None:
    if not settings:
        return
    apply_advanced_matplotlib_style(ax, settings)
    title = advanced_element_text(settings, "titleElement")
    x_label = advanced_element_text(settings, "xLabelElement")
    y_label = advanced_element_text(settings, "yLabelElement")
    title_size = advanced_element_number(settings, "titleElement", "size")
    x_axis_size = advanced_element_number(settings, "xLabelElement", "size")
    y_axis_size = advanced_element_number(settings, "yLabelElement", "size")
    x_tick_size = advanced_number(settings, "xTickLabelSize", 0.0)
    y_tick_size = advanced_number(settings, "yTickLabelSize", 0.0)
    x_tick_rotation = advanced_optional_number(settings, "xTickLabelRotation")
    y_tick_rotation = advanced_optional_number(settings, "yTickLabelRotation")
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
    for element_key, artist in (
        ("titleElement", title_obj),
        ("xLabelElement", ax.xaxis.label),
        ("yLabelElement", ax.yaxis.label),
    ):
        _offset_text(
            artist,
            ax.figure,
            advanced_element_number(settings, element_key, "xOffset"),
            advanced_element_number(settings, element_key, "yOffset"),
        )
    if x_tick_size > 0:
        ax.tick_params(axis="x", labelsize=x_tick_size)
    if y_tick_size > 0:
        ax.tick_params(axis="y", labelsize=y_tick_size)
    x_tick_color = advanced_color_text(settings, "xTickLabelColor")
    y_tick_color = advanced_color_text(settings, "yTickLabelColor")
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


def advanced_plotly_layout(
    settings: dict[str, Any] | None,
    width_px: int = 960,
    height_px: int = 540,
) -> dict[str, Any]:
    if not settings:
        return {}
    layout: dict[str, Any] = {}
    theme = _advanced_theme(settings)
    background = advanced_color_text(settings, "backgroundColor")
    transparent = _advanced_bool(settings, "transparentBackground", False)
    title = advanced_element_text(settings, "titleElement")
    x_label = advanced_element_text(settings, "xLabelElement")
    y_label = advanced_element_text(settings, "yLabelElement")
    title_size = advanced_element_number(settings, "titleElement", "size")
    x_axis_size = advanced_element_number(settings, "xLabelElement", "size")
    y_axis_size = advanced_element_number(settings, "yLabelElement", "size")
    x_tick_size = advanced_number(settings, "xTickLabelSize", 0.0)
    y_tick_size = advanced_number(settings, "yTickLabelSize", 0.0)
    x_tick_rotation = advanced_optional_number(settings, "xTickLabelRotation")
    y_tick_rotation = advanced_optional_number(settings, "yTickLabelRotation")
    legend_size = advanced_number(settings, "legendFontSize", 0.0)
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
    title_x = advanced_element_number(settings, "titleElement", "xOffset")
    title_y = advanced_element_number(settings, "titleElement", "yOffset")
    if title_x:
        # Plotly takes a title position only between 0 and 1 of the figure;
        # a nudge past the edge stops at the edge rather than refusing the plot.
        layout["title_x"] = min(1.0, max(0.0, 0.5 + _plotly_pixel_fraction(title_x, width_px)))
    if title_y:
        layout.update(_plotly_title_offset(title_y, height_px))
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
        tick_colour = advanced_color_text(settings, colour_key)
        if tick_colour:
            layout.setdefault(axis_key, {}).setdefault("tickfont", {})["color"] = tick_colour

    if _advanced_optional_bool(settings, "titleVisible") is False:
        layout["title"] = ""
    if _advanced_optional_bool(settings, "legendVisible") is False:
        layout["showlegend"] = False
    legend_title = advanced_text(settings, "legendTitle")
    if legend_title is not None:
        layout.setdefault("legend", {}).setdefault("title", {})["text"] = legend_title
    legend_colour = advanced_color_text(settings, "legendTextColor")
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
    legend_x = advanced_number(settings, "legendXOffset", 0.0)
    legend_y = advanced_number(settings, "legendYOffset", 0.0)
    if legend_x or legend_y:
        # Plotly's own bounds for a legend position.
        layout.setdefault("legend", {})["x"] = min(3.0, max(-2.0, 1.02 + _plotly_pixel_fraction(legend_x, width_px)))
        layout.setdefault("legend", {})["y"] = min(3.0, max(-2.0, 1.0 + _plotly_pixel_fraction(legend_y, height_px)))
    return layout

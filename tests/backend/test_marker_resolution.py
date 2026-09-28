"""A dot's appearance: the plot's default, the general setting, then its group's.

Three layers, in that order. The panel offers a general control and, on a plot
whose points are drawn one condition at a time, an override per condition.
Choosing a general value clears the overrides -- that part lives in the panel --
so what the backend has to guarantee is only the resolution: an override wins
over the general setting, a general setting wins over the plot's own default,
and a shape means the same marker in the figure and in the interactive plot
beside it.

`markerColor` is the exception and deliberately so. On a plot that colours its
points by condition, the colour comes from the condition palette and that is the
only place it is set; the general dot colour is for the plots that have no such
palette. So a colour passed in by the renderer always wins.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import matplotlib

matplotlib.use("Agg")

from app.services.plot_styling import (
    DEFAULT_MARKER_SHAPE,
    MARKER_SHAPES,
    advanced_color_map,
    marker_area,
    marker_style,
    plotly_marker,
    resolve_marker,
    resolve_marker_shape,
)


def diameter(style: dict) -> float:
    return float(style["s"]) ** 0.5


# --- the three layers ----------------------------------------------------------


def test_with_nothing_set_the_plot_keeps_its_own_default() -> None:
    style = marker_style(None, size=3.0, alpha=0.5)
    assert diameter(style) == pytest.approx(3.0)
    assert style["alpha"] == pytest.approx(0.5)
    assert style["marker"] == MARKER_SHAPES[DEFAULT_MARKER_SHAPE][0]


def test_a_general_setting_beats_the_plot_default() -> None:
    style = marker_style({"markerSize": 9, "markerAlpha": 0.2}, size=3.0, alpha=0.5)
    assert diameter(style) == pytest.approx(9.0)
    assert style["alpha"] == pytest.approx(0.2)


def test_a_group_override_beats_the_general_setting() -> None:
    settings = {"markerSize": 9, "conditionMarkerSizes": {"A": 20}}
    assert diameter(marker_style(settings, size=3.0, alpha=1.0, group="A")) == pytest.approx(20)
    assert diameter(marker_style(settings, size=3.0, alpha=1.0, group="B")) == pytest.approx(9)
    assert diameter(marker_style(settings, size=3.0, alpha=1.0)) == pytest.approx(9)


def test_an_override_for_one_property_leaves_the_others_general() -> None:
    """Setting A's shape must not also pin A's size."""
    settings = {
        "markerSize": 9,
        "markerAlpha": 0.4,
        "conditionMarkerShapes": {"A": "triangle-up"},
    }
    style = marker_style(settings, size=3.0, alpha=1.0, group="A")
    assert style["marker"] == "^"
    assert diameter(style) == pytest.approx(9.0)
    assert style["alpha"] == pytest.approx(0.4)


@pytest.mark.parametrize("empty", [None, "", {}])
def test_an_empty_override_is_not_an_override(empty) -> None:
    settings = {"markerSize": 9, "conditionMarkerSizes": {"A": empty} if empty != {} else {}}
    assert diameter(marker_style(settings, size=3.0, alpha=1.0, group="A")) == pytest.approx(9)


def test_a_malformed_override_map_is_ignored_rather_than_raising() -> None:
    """The settings arrive as untyped JSON off a query string."""
    for broken in ("not a map", 7, ["A", 2]):
        style = marker_style(
            {"markerSize": 9, "conditionMarkerSizes": broken}, size=3.0, alpha=1.0, group="A"
        )
        assert diameter(style) == pytest.approx(9)


# --- shapes --------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(MARKER_SHAPES))
def test_every_shape_has_a_spelling_in_both_renderers(name: str) -> None:
    matplotlib_name = resolve_marker_shape(name)
    plotly_name = resolve_marker_shape(name, "plotly")
    assert matplotlib_name and plotly_name
    from matplotlib.markers import MarkerStyle

    MarkerStyle(matplotlib_name)  # raises if matplotlib does not know it

    import plotly.graph_objects as go

    go.Scatter(marker={"symbol": plotly_name})  # raises if plotly does not


def test_an_unknown_shape_falls_back_rather_than_raising() -> None:
    """The field is a select today; it is still free text on the wire."""
    assert resolve_marker_shape("triangel") == MARKER_SHAPES[DEFAULT_MARKER_SHAPE][0]
    assert resolve_marker_shape(None) == MARKER_SHAPES[DEFAULT_MARKER_SHAPE][0]


def test_the_two_renderers_agree_on_size_and_shape() -> None:
    settings = {"markerSize": 7, "markerShape": "diamond", "markerAlpha": 0.3}
    static = marker_style(settings, size=3.0, alpha=1.0)
    interactive = plotly_marker(settings, size=3.0, alpha=1.0)
    assert diameter(static) == pytest.approx(interactive["size"])
    assert static["marker"] == "D" and interactive["symbol"] == "diamond"
    assert static["alpha"] == pytest.approx(interactive["opacity"])


# --- colour --------------------------------------------------------------------


def test_the_palette_colour_wins_over_the_general_dot_colour() -> None:
    style = marker_style({"markerColor": "#123456"}, size=3, alpha=1, color="#abcdef")
    assert style["color"] == "#abcdef"


def test_the_general_dot_colour_is_used_when_the_plot_has_no_palette() -> None:
    assert marker_style({"markerColor": "#123456"}, size=3, alpha=1)["color"] == "#123456"
    assert marker_style(None, size=3, alpha=1, color_default="black")["color"] == "black"


def test_a_data_coloured_scatter_is_never_handed_one_colour() -> None:
    """A colour-mapped scatter cannot also take a single colour."""
    style = marker_style({"markerColor": "#123456"}, size=3, alpha=1, use_color=False)
    assert "color" not in style


# --- outline -------------------------------------------------------------------


def test_the_outline_is_off_until_it_is_asked_for() -> None:
    assert marker_style(None, size=3, alpha=1)["edgecolors"] == "none"
    style = marker_style({"markerEdgeWidth": 0.5}, size=3, alpha=1)
    assert style["linewidths"] == pytest.approx(0.5)
    assert style["edgecolors"] == "#000000"


def test_a_plot_with_its_own_outline_keeps_it_as_the_default() -> None:
    style = marker_style(None, size=3, alpha=1, edge_width_default=0.4, edge_color_default="grey")
    assert style["linewidths"] == pytest.approx(0.4)
    assert style["edgecolors"] == "grey"


def test_a_plot_can_name_its_own_general_keys() -> None:
    """The single-protein boxplot's points predate the shared controls."""
    appearance = resolve_marker(
        {"boxPointSize": 11, "markerSize": 2},
        size=4.5,
        alpha=0.8,
        size_key="boxPointSize",
        alpha_key="boxPointAlpha",
    )
    assert appearance.diameter == pytest.approx(11)


def test_a_condition_override_still_reaches_a_plot_with_its_own_keys() -> None:
    appearance = resolve_marker(
        {"boxPointSize": 11, "conditionMarkerSizes": {"WT": 3}},
        size=4.5,
        alpha=0.8,
        group="WT",
        size_key="boxPointSize",
    )
    assert appearance.diameter == pytest.approx(3)


# --- the colour scale ----------------------------------------------------------


def test_the_colour_scale_control_is_honoured_and_validated() -> None:
    assert advanced_color_map({"correlationColorMap": "viridis"}, "plasma") == "viridis"
    assert advanced_color_map({"correlationColorMap": "vir"}, "plasma") == "plasma"
    assert advanced_color_map(None, "plasma") == "plasma"


def test_marker_area_is_still_the_square_of_the_diameter() -> None:
    assert marker_area(6) == pytest.approx(36)
    assert marker_area(0) == pytest.approx(1.0), "a marker is never invisible by rounding"

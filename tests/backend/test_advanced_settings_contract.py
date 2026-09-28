"""A setting in the plot appearance panel changes what it names and nothing else.

The panel used to write every displayed default of the frame and grid into the
stored settings on the first edit of anything, and the backend restyled the
whole grid or frame whenever any one of their keys was present. Together that
meant a title edit also recoloured the grid, and switching advanced mode on
changed a plot nobody had touched. These tests hold both appliers -- the
matplotlib one and the Plotly one -- to the rule the panel now relies on.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402

from app.services.plot_styling import (
    advanced_plotly_layout,
    apply_advanced_matplotlib_style,
)


@pytest.mark.parametrize("route_name,renderer,settings", [
    ("qc_boxplot_route", "qc_boxplot_plot", {
        "boxBorderColor": "#123456", "boxMedianColor": "#654321",
        "boxOutlierColor": "#abcdef", "boxOutlierEdgeColor": "#fedcba", "boxOutlierSize": 7,
    }),
    ("qc_correlation_route", "qc_correlation_plot", {"correlationColorMap": "viridis"}),
])
def test_qc_styles_have_one_authoritative_transport(monkeypatch, route_name, renderer, settings):
    import inspect
    import json
    from app.api import routes_plots

    received = {}
    def render(**kwargs):
        received.update(kwargs)
        return b"image"
    monkeypatch.setattr(routes_plots, renderer, render)
    route = getattr(routes_plots, route_name)
    assert not set(settings).intersection(inspect.signature(route).parameters)
    response = route(kind="protein", advanced=json.dumps(settings))
    assert response.body == b"image"
    assert received["advanced"] == settings


def _figure(*, grid: str | None):
    fig, ax = plt.subplots()
    ax.plot([0, 1, 2], [0, 1, 4])
    if grid:
        ax.grid(True, axis=grid, color="#123456", linewidth=0.5, linestyle=":")
    return fig, ax


def _grid_state(ax):
    def one(axis):
        lines = [line for line in axis.get_gridlines() if line.get_visible()]
        return bool(lines), (to_hex(lines[0].get_color()) if lines else None)

    return one(ax.xaxis), one(ax.yaxis)


def _frame_state(ax):
    return {
        name: (spine.get_visible(), to_hex(spine.get_edgecolor(), keep_alpha=False))
        for name, spine in ax.spines.items()
    }


@pytest.mark.parametrize("grid", [None, "x", "y", "both"])
def test_a_grid_colour_recolours_and_does_not_switch_the_grid(grid):
    fig, ax = _figure(grid=grid)
    before = _grid_state(ax)
    apply_advanced_matplotlib_style(ax, {"gridLineColor": "#ff0000"})
    after = _grid_state(ax)
    for (was_on, _), (now_on, colour) in zip(before, after):
        assert now_on == was_on, "a colour must not switch a grid on or off"
        if now_on:
            assert colour == "#ff0000"
    plt.close(fig)


def test_grid_placement_switches_on_and_uses_what_is_named():
    fig, ax = _figure(grid=None)
    apply_advanced_matplotlib_style(
        ax, {"gridLineVisible": True, "gridLineAxis": "x", "gridLineColor": "#00ff00"}
    )
    (x_on, x_colour), (y_on, _) = _grid_state(ax)
    assert x_on and not y_on
    assert x_colour == "#00ff00"
    plt.close(fig)


def test_hiding_one_side_leaves_the_others_as_they_were():
    fig, ax = _figure(grid=None)
    for spine in ax.spines.values():
        spine.set_color("#333333")
    before = _frame_state(ax)
    apply_advanced_matplotlib_style(
        ax,
        {"axisLineTop": False, "axisLineRight": True, "axisLineBottom": True, "axisLineLeft": True},
    )
    after = _frame_state(ax)
    assert after["top"][0] is False
    for side in ("left", "right", "bottom"):
        assert after[side] == before[side], f"{side} changed"
    plt.close(fig)


def test_a_frame_colour_recolours_and_does_not_show_or_hide_a_side():
    fig, ax = _figure(grid=None)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    apply_advanced_matplotlib_style(ax, {"axisLineColor": "#ff0000"})
    after = _frame_state(ax)
    assert after["top"][0] is False and after["right"][0] is False
    assert after["left"] == (True, "#ff0000")
    assert after["bottom"] == (True, "#ff0000")
    plt.close(fig)


def test_empty_settings_write_nothing_into_a_plotly_layout():
    assert advanced_plotly_layout({}) == {}
    assert advanced_plotly_layout(None) == {}


def test_a_title_edit_writes_no_grid_or_frame_into_a_plotly_layout():
    layout = advanced_plotly_layout({"titleElement": {"text": "Edited"}})
    for axis in ("xaxis", "yaxis"):
        written = set(layout.get(axis, {}))
        assert not written & {
            "showgrid", "gridcolor", "gridwidth", "griddash",
            "showline", "linecolor", "linewidth", "ticks", "tickcolor", "mirror",
        }, f"{axis} got {written}"


def test_a_plotly_grid_colour_does_not_switch_the_grid_or_restyle_it():
    layout = advanced_plotly_layout({"gridLineColor": "#ff0000"})
    for axis in ("xaxis", "yaxis"):
        assert layout[axis] == {"gridcolor": "#ff0000"}


def test_a_plotly_frame_colour_does_not_draw_a_frame():
    layout = advanced_plotly_layout({"axisLineColor": "#ff0000"})
    for axis in ("xaxis", "yaxis"):
        assert "showline" not in layout[axis]
        assert "ticks" not in layout[axis]
        assert layout[axis]["linecolor"] == "#ff0000"


def test_plotly_sides_decide_lines_and_ticks_and_nothing_about_colour():
    layout = advanced_plotly_layout(
        {"axisLineTop": False, "axisLineRight": False, "axisLineBottom": True, "axisLineLeft": True}
    )
    assert layout["xaxis"]["showline"] is True and layout["xaxis"]["mirror"] is False
    assert layout["yaxis"]["showline"] is True and layout["yaxis"]["mirror"] is False
    for axis in ("xaxis", "yaxis"):
        assert "linecolor" not in layout[axis] and "tickcolor" not in layout[axis]

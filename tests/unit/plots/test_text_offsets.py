"""A title or axis label nudged in the appearance panel moves by that much, and the plot still draws.

Two bugs made the offsets unusable. On the static plots the label was moved by
setting coordinates read back in the wrong system -- an axis label's automatic
position is partly in display pixels, and it was written back as axes
fractions -- so a 2 px nudge sent it off the canvas and the missing-value
heatmap refused to render ("Plot labels do not fit"). On the interactive plots
a raised title was written as a position above 1, which Plotly refuses, so every
interactive plot answered 400 once the title was moved up at all.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import pytest  # noqa: E402

from app.services.plot_styling import advanced_plotly_layout, apply_advanced_axes  # noqa: E402


def _figure():
    fig, ax = plt.subplots(figsize=(4, 3), dpi=100)
    ax.plot([0, 1], [0, 1])
    ax.set_title("Title")
    ax.set_xlabel("X label")
    ax.set_ylabel("Y label")
    return fig, ax


def _extents(fig, ax):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    return {
        "title": ax.title.get_window_extent(renderer),
        "x": ax.xaxis.label.get_window_extent(renderer),
        "y": ax.yaxis.label.get_window_extent(renderer),
    }


@pytest.mark.parametrize("dx,dy", [(10, 0), (0, 10), (-7, -12), (2, 2)])
def test_each_label_moves_by_the_pixels_asked_for(dx: float, dy: float) -> None:
    fig, ax = _figure()
    before = _extents(fig, ax)
    element = {"xOffset": dx, "yOffset": dy}
    apply_advanced_axes(ax, {"titleElement": element, "xLabelElement": element, "yLabelElement": element})
    after = _extents(fig, ax)
    for name in ("title", "x", "y"):
        assert after[name].x0 - before[name].x0 == pytest.approx(dx, abs=0.01), name
        assert after[name].y0 - before[name].y0 == pytest.approx(dy, abs=0.01), name
    plt.close(fig)


def test_applying_the_settings_twice_moves_a_label_once() -> None:
    """Several renderers style their axes twice; the nudge must not double."""
    fig, ax = _figure()
    before = _extents(fig, ax)
    settings = {"xLabelElement": {"yOffset": -5}}
    apply_advanced_axes(ax, settings)
    apply_advanced_axes(ax, settings)
    assert _extents(fig, ax)["x"].y0 - before["x"].y0 == pytest.approx(-5, abs=0.01)
    plt.close(fig)


def test_a_nudged_axis_label_stays_clear_of_its_tick_labels() -> None:
    """The label keeps its automatic place beside the ticks; the nudge is on top of it."""
    fig, ax = _figure()
    apply_advanced_axes(ax, {"xLabelElement": {"xOffset": 2}})
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lowest_tick = min(label.get_window_extent(renderer).y0 for label in ax.get_xticklabels() if label.get_text())
    assert ax.xaxis.label.get_window_extent(renderer).y1 <= lowest_tick + 0.01
    plt.close(fig)


@pytest.mark.parametrize("element", ["xLabelElement", "yLabelElement"])
@pytest.mark.parametrize("offset", [-2, 2])
def test_the_missing_value_heatmap_draws_with_a_nudged_axis_label(client, element: str, offset: int) -> None:
    advanced = json.dumps({element: {"xOffset": offset, "yOffset": offset}})
    response = client.get("/api/plots/completeness/protein/missing-heatmap.png", params={"advanced": advanced})
    assert response.status_code == 200, response.text[:300]


@pytest.mark.parametrize("offset", [-300, -60, -20, -1, 1, 20, 60, 300])
def test_an_interactive_title_takes_any_offset_plotly_can_draw(offset: int) -> None:
    layout = advanced_plotly_layout({"titleElement": {"text": "T", "xOffset": offset, "yOffset": offset}}, 800, 500)
    go.Figure(layout=layout)  # Plotly validates every property here.
    assert 0.0 <= layout["title_x"] <= 1.0 and 0.0 <= layout["title_y"] <= 1.0


def test_raising_the_title_widens_its_gap_above_the_plot() -> None:
    gaps = [
        advanced_plotly_layout({"titleElement": {"yOffset": offset}}, 800, 500)["title_pad"]["b"]
        for offset in (5, 30, 90)
    ]
    assert gaps[1] - gaps[0] == 25 and gaps[2] - gaps[1] == 60
    assert advanced_plotly_layout({"titleElement": {"yOffset": 30}}, 800, 500)["title_automargin"] is True


def test_interactive_plots_draw_with_a_raised_title(client) -> None:
    advanced = json.dumps({"titleElement": {"text": "Raised", "yOffset": 15}})
    for path, params in (
        ("/api/plots/stats/protein/volcano.html", {"condition1": "WT", "condition2": "GRK"}),
        ("/api/plots/qc/protein/pca-interactive.html", {}),
        ("/api/plots/comparison/protein/pearson.html", {"mode": "Condition", "condition1": "WT", "condition2": "GRK"}),
    ):
        response = client.get(path, params={**params, "advanced": advanced})
        assert response.status_code == 200, (path, response.text[:300])

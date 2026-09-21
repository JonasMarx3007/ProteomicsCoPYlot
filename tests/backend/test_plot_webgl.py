"""Interactive figures must never depend on WebGL to appear.

Plotly falls back to a bare "webgl is not supported by your browser" message on
a machine without hardware acceleration, which is indistinguishable from a
broken tool. Every interactive renderer therefore goes out as SVG.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytest

from app.services.plot_webgl import (
    WEBGL_POINT_THRESHOLD,
    figure_point_count,
    force_svg_rendering,
)

SERVICES = Path(__file__).resolve().parents[2] / "backend" / "app" / "services"


def test_no_renderer_asks_for_webgl_by_hand():
    offenders = {
        path.name: [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if "go.Scattergl(" in line or 'render_mode="webgl"' in line
        ]
        for path in SERVICES.glob("*.py")
    }
    assert not {name: lines for name, lines in offenders.items() if lines}


def test_plotly_express_autoswitch_to_webgl_is_undone():
    # px.scatter picks scattergl for itself above ~1000 points.
    frame = pd.DataFrame({"x": np.arange(5_000, dtype=float), "y": np.arange(5_000, dtype=float)})
    fig = px.scatter(frame, x="x", y="y")
    assert fig.data[0].type == "scattergl", "plotly no longer auto-switches; the guard is still wanted"

    converted = force_svg_rendering(fig)
    assert [trace.type for trace in converted.data] == ["scatter"]
    assert len(converted.data[0].x) == 5_000, "points are kept, only the renderer changes"


def test_explicit_webgl_traces_are_converted_and_keep_their_payload():
    fig = go.Figure()
    fig.add_trace(
        go.Scattergl(
            x=[1.0, 2.0, 3.0],
            y=[2.0, 4.0, 6.0],
            mode="markers",
            marker=dict(size=6, color="#1f77b4"),
            customdata=np.array([["a"], ["b"], ["c"]], dtype=object),
            hovertemplate="Feature: %{customdata[0]}<extra></extra>",
            name="Points",
        )
    )
    fig.add_trace(go.Scatter(x=[1.0, 3.0], y=[2.0, 6.0], mode="lines", name="Fit"))
    fig.update_layout(title="Pearson Correlation: a vs b", paper_bgcolor="#fff")

    converted = force_svg_rendering(fig)
    assert [trace.type for trace in converted.data] == ["scatter", "scatter"]
    points = converted.data[0]
    assert list(points.x) == [1.0, 2.0, 3.0]
    assert points.marker.color == "#1f77b4"
    assert points.hovertemplate == "Feature: %{customdata[0]}<extra></extra>"
    assert converted.layout.title.text == "Pearson Correlation: a vs b"
    assert converted.layout.paper_bgcolor == "#fff"


def test_three_dimensional_traces_are_left_alone():
    # scatter3d has no SVG implementation, so there is nothing to fall back to.
    fig = go.Figure(go.Scatter3d(x=[1, 2], y=[1, 2], z=[1, 2], mode="markers"))
    assert [trace.type for trace in force_svg_rendering(fig).data] == ["scatter3d"]


def test_large_scatters_still_render_as_svg_rather_than_warn():
    size = WEBGL_POINT_THRESHOLD + 10
    fig = go.Figure(go.Scattergl(x=np.arange(size, dtype=float), y=np.arange(size, dtype=float), mode="markers"))
    converted = force_svg_rendering(fig)
    assert [trace.type for trace in converted.data] == ["scatter"]
    # Above the threshold we accept the slower figure; no point is dropped.
    assert figure_point_count(converted) == size


@pytest.mark.parametrize(
    "module_name",
    ["plot_images", "stats_tools", "comparison_tools", "peptide_tools", "phospho_tools"],
)
def test_every_interactive_renderer_serialises_svg_traces(module_name, monkeypatch):
    """Every module's HTML entry point applies the policy, not just some of them.

    Asserted on the figure handed to ``to_html`` rather than on the HTML text:
    the embedded plotly.js bundle and the layout template both mention
    ``scattergl`` whatever the figure contains.
    """
    module = importlib.import_module(f"app.services.{module_name}")
    serialised: dict[str, list[str]] = {}

    def capture_to_html(self, **kwargs):
        serialised["types"] = [trace.type for trace in self.data]
        return "<div id='plot'></div>"

    monkeypatch.setattr(go.Figure, "to_html", capture_to_html)
    frame = pd.DataFrame({"x": np.arange(3_000, dtype=float), "y": np.arange(3_000, dtype=float)})
    module._plotly_html(px.scatter(frame, x="x", y="y"))
    assert serialised["types"] == ["scatter"]

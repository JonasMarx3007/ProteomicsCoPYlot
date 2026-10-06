"""Interactive figures must never depend on WebGL to appear.

Plotly falls back to a bare "webgl is not supported by your browser" message on
a machine without hardware acceleration, which is indistinguishable from a
broken tool. Every interactive renderer therefore goes out as SVG.
"""

from __future__ import annotations

import importlib

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



# --- what the browser receives -------------------------------------------------
#
# Every interactive route is requested on a loaded project and the trace types
# are read out of the `Plotly.newPlot(...)` call in the HTML that comes back --
# the payload the browser actually draws, however the server produced it. A
# renderer that builds `go.Scattergl` or asks plotly express for
# `render_mode="webgl"` and skips the conversion shows up here as a `*gl` trace.

SAMPLE_1 = "[6] 20240822_nElute_tims1_JM_HEK293_WP_WT_1_Slot1-61_1_8064.d.PG.Log2Quantity"
SAMPLE_2 = "[7] 20240822_nElute_tims1_JM_HEK293_WP_WT_2_Slot1-62_1_8065.d.PG.Log2Quantity"
CONTRAST = {"condition1": "WT", "condition2": "GRK"}

INTERACTIVE_GET_ROUTES = [
    *[(f"/api/plots/stats/{kind}/volcano.html", CONTRAST) for kind in ("protein", "phospho", "phosprot")],
    *[(f"/api/plots/stats/{kind}/simulation.html", CONTRAST) for kind in ("protein", "phospho", "phosprot")],
    *[(f"/api/plots/qc/{kind}/pca-interactive.html", {}) for kind in ("protein", "phospho", "phosprot")],
    *[(f"/api/plots/qc/{kind}/abundance-interactive.html", {}) for kind in ("protein", "phospho", "phosprot")],
    ("/api/plots/phospho/phosprot-regulation.html", CONTRAST),
    ("/api/plots/comparison/protein/pearson.html", {"sample1": SAMPLE_1, "sample2": SAMPLE_2}),
]


def _browser_trace_types(html: str) -> list[str]:
    """The `type` of every trace in the page's last `Plotly.newPlot` call.

    The page embeds plotly.js itself, which mentions `newPlot` too, so the
    figure's own call is the last one. Its arguments are the div id, then the
    trace array as JSON.
    """
    import json
    import re

    start = html.rfind("Plotly.newPlot(")
    assert start >= 0, "the response holds no plotly figure"
    div_id = re.compile(r'\s*"[^"]*"\s*,\s*').match(html, start + len("Plotly.newPlot("))
    assert div_id is not None, "the plotly call has an unexpected shape"
    traces, _ = json.JSONDecoder().raw_decode(html, div_id.end())
    return [trace.get("type", "scatter") for trace in traces]


def _assert_no_webgl(response, label: str) -> None:
    assert response.status_code == 200, f"{label}: {response.status_code} {response.text[:200]}"
    types = _browser_trace_types(response.text)
    assert types, f"{label}: the figure has no traces"
    webgl = [kind for kind in types if kind.endswith("gl")]
    assert not webgl, f"{label} sends WebGL traces to the browser: {webgl}"


@pytest.mark.parametrize("path,params", INTERACTIVE_GET_ROUTES, ids=[path for path, _ in INTERACTIVE_GET_ROUTES])
def test_no_interactive_route_sends_webgl_to_the_browser(client, path: str, params: dict) -> None:
    _assert_no_webgl(client.get(path, params=params), path)


def test_the_uploaded_kinase_library_volcano_sends_no_webgl(client) -> None:
    table = "Kinase,Log2(Frequency Factor),Adjusted p-value\nAKT1,1.5,0.01\nMAPK1,-1.0,0.2\n"
    response = client.post(
        "/api/plots/phospho/ksea-volcano.html",
        files={"fileSt": ("st.csv", table, "text/csv"), "fileTnc": ("tnc.csv", table, "text/csv")},
    )
    _assert_no_webgl(response, "ksea-volcano.html")


def test_the_interactive_retention_time_plot_sends_no_webgl(client, tmp_path) -> None:
    from app.services.dataset_store import save_peptide_path

    # Enough precursors that plotly express would pick WebGL on its own.
    rng = np.random.default_rng(1)
    rows = [
        {
            "File.Name": f"run{run}", "Stripped.Sequence": f"PEPTIDE{i}K", "Modified.Sequence": f"PEPTIDE{i}K",
            "Precursor.Id": f"PEPTIDE{i}K2", "Precursor.Quantity": float(i + 1),
            "RT": float(rng.uniform(5, 60)), "Predicted.RT": float(rng.uniform(5, 60)),
        }
        for run in range(3) for i in range(1_500)
    ]
    path = tmp_path / "peptides.tsv"
    pd.DataFrame(rows).to_csv(path, sep="\t", index=False)
    save_peptide_path(str(path))
    _assert_no_webgl(client.get("/api/plots/peptide/rt-interactive.html"), "rt-interactive.html")


def test_the_control_volcano_sends_no_webgl(client) -> None:
    """The example has two conditions; the control volcano needs four."""
    from app.schemas.annotation import AnnotationFilterConfig
    from app.services.annotation_store import save_annotation

    rng = np.random.default_rng(2)
    conditions = ["A", "Actrl", "B", "Bctrl"]
    samples = [f"{condition}_{replicate}" for condition in conditions for replicate in (1, 2, 3)]
    frame = pd.DataFrame(rng.normal(20, 1, (2_000, len(samples))), columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(len(frame))])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(len(frame))])
    metadata = pd.DataFrame({"sample": samples, "condition": [s.rsplit("_", 1)[0] for s in samples]})
    save_annotation(
        kind="protein", source_data=frame, metadata=metadata, log2_data=frame, filtered_data=frame,
        is_log2_transformed=True, metadata_source="uploaded", filter_config=AnnotationFilterConfig(),
        auto_detected=False, warnings=[], log2_auto_detected=False,
    )
    response = client.get(
        "/api/plots/stats/protein/volcano-control.html",
        params={"condition1": "A", "condition2": "B", "condition1Control": "Actrl", "condition2Control": "Bctrl"},
    )
    _assert_no_webgl(response, "volcano-control.html")


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

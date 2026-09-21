"""One shared decision about how interactive scatter figures reach the browser.

Plotly draws dense scatters through WebGL: ``px.scatter`` switches to
``scattergl`` by itself above roughly a thousand points, and a couple of
renderers used to ask for ``go.Scattergl`` outright. WebGL is much faster, but
it needs hardware acceleration. On a machine where that is off - a remote
desktop, a locked-down laptop, a browser with the GPU on its blocklist - every
one of those figures dies with "webgl is not supported by your browser" and the
user sees nothing at all.

The renderer runs on the server and cannot ask the client whether WebGL works,
so the safe default is the one that works everywhere: plain SVG traces.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The point count above which SVG stops being free. Plotly's own switch happens
# around 1_000 points, which is far too eager: SVG handles tens of thousands of
# markers without anyone noticing. Around this many markers - one DOM node each
# - panning and hovering start to feel heavy on a mid-range laptop.
#
# Above the threshold we still render SVG and accept the slower figure, rather
# than thinning what is drawn. These are analysis figures (correlation,
# retention time, abundance rank) where a dropped point is a dropped feature,
# and a figure that quietly shows less data is worse than one that takes a
# moment to appear. Crossing the threshold is logged for the operator; the user
# gets a figure, never a warning, and never a blank WebGL error.
WEBGL_POINT_THRESHOLD = 50_000

# WebGL trace types with an exact SVG twin. 3-D and surface traces are
# deliberately absent: Plotly has no SVG implementation for them, so there is
# nothing to fall back to.
_WEBGL_TO_SVG = {
    "scattergl": "scatter",
    "scatterpolargl": "scatterpolar",
    "heatmapgl": "heatmap",
}


def _trace_point_count(trace) -> int:
    for axis in ("x", "y"):
        values = trace.get(axis) if isinstance(trace, dict) else getattr(trace, axis, None)
        if isinstance(values, dict) and "bdata" in values:
            # Plotly can carry an array as base64 plus a dtype.
            import base64

            import numpy as np

            try:
                itemsize = np.dtype(str(values.get("dtype", "f8"))).itemsize
                return len(base64.b64decode(values["bdata"])) // max(1, itemsize)
            except Exception:
                return 0
        try:
            return len(values)
        except TypeError:
            continue
    return 0


def figure_point_count(fig) -> int:
    """Largest number of points in any single trace of ``fig``."""
    try:
        traces = list(fig.data)
    except Exception:
        return 0
    return max((_trace_point_count(trace) for trace in traces), default=0)


def force_svg_rendering(fig):
    """Return ``fig`` with every WebGL scatter trace replaced by its SVG twin.

    Called from the one place each module turns a figure into HTML, so new
    renderers inherit it without having to remember ``render_mode="svg"``.
    Returns the figure to use; the argument is left untouched when a rebuild is
    needed, and returned unchanged when nothing is WebGL.
    """
    try:
        traces = list(fig.data)
    except Exception:  # pragma: no cover - not a plotly figure
        return fig

    points = figure_point_count(fig)
    if any(getattr(trace, "type", None) in _WEBGL_TO_SVG for trace in traces):
        import plotly.graph_objects as go

        # Per-trace JSON rather than fig.to_dict(): it keeps the arrays as they
        # are instead of base64-encoding them on the way through.
        rebuilt = []
        for trace in traces:
            spec = trace.to_plotly_json()
            replacement = _WEBGL_TO_SVG.get(spec.get("type"))
            if replacement is not None:
                spec["type"] = replacement
            rebuilt.append(spec)
        fig = go.Figure(data=rebuilt, layout=fig.layout, frames=fig.frames)

    if points > WEBGL_POINT_THRESHOLD:
        logger.info(
            "Rendering %s points as SVG: above the %s point threshold WebGL would be "
            "faster, but it fails outright without hardware acceleration.",
            points,
            WEBGL_POINT_THRESHOLD,
        )
    return fig

"""Interactive plots shown in the app load plotly.js once, not once per plot.

Every interactive plot is a self-contained HTML page with plotly.js inline,
about 4.8 MB each. That stays true for downloads and exports. For the app's own
display the frontend asks for the shared form (header SHARED_PLOTLY_HEADER):
the server replaces the inline bundle with a marker and names the versioned
asset, which the frontend fetches once, caches, and puts back inline before
showing the page. The sandbox and its CSP (inline scripts only) are unchanged.
"""
from __future__ import annotations

from functools import lru_cache

SHARED_PLOTLY_HEADER = "x-copylot-shared-plotly"
PLOTLY_ASSET_HEADER = "X-CoPYlot-Plotly-Asset"
PLOTLY_MARKER = "/*copylot-shared-plotly*/"


@lru_cache(maxsize=1)
def plotly_bundle() -> tuple[str, str]:
    """(version, plotly.min.js source) of the installed plotly package."""
    import plotly
    from plotly.offline import get_plotlyjs

    return str(plotly.__version__), get_plotlyjs()


def plotly_asset_path() -> str:
    version, _ = plotly_bundle()
    return f"/api/runtime/plotly-{version}.js"


def share_plotly(html: str) -> str | None:
    """The page with its inline plotly.js replaced by the marker, or None if it has none."""
    _, source = plotly_bundle()
    if source not in html:
        return None
    return html.replace(source, PLOTLY_MARKER, 1)

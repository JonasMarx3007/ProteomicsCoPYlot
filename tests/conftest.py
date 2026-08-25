from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["COPYLOT_TOOL_ACCESS_ENABLED"] = "0"
os.environ["COPYLOT_VIEWER_PORTAL_ENABLED"] = "0"
os.environ["COPYLOT_SESSION_ISOLATION"] = "0"
os.environ["COPYLOT_ALLOWED_HOSTS"] = "testserver"

import matplotlib

matplotlib.use("Agg")

import plotly.io

plotly.io.renderers.default = "plotly_mimetype"

_HEADLESS_RPROFILE = Path(tempfile.gettempdir()) / "copylot_headless_rprofile.R"
_HEADLESS_RPROFILE.write_text(
    "options(device = function(...) grDevices::pdf(NULL))\n"
    "options(browser = function(...) invisible(NULL))\n",
    encoding="utf-8",
)
os.environ["R_PROFILE_USER"] = str(_HEADLESS_RPROFILE)

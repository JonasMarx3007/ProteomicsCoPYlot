from __future__ import annotations

import os
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

import pytest

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


@pytest.fixture(scope="module", autouse=True)
def preserve_analysis_state_between_modules():
    """Viewer fixtures may share state within a module, never with the next one.

    Use the same five store snapshots as atomic restore, including active
    packages/profiles. ExitStack restores them even if setup or a test fails.
    Imports are delayed until collection has established the backend path.
    """
    from app.services import restore_state

    with ExitStack() as cleanup:
        for store in ("dataset", "metadata", "annotation", "condition_palette", "peptide_metadata"):
            # Production snapshots are references intended for atomic replacement;
            # tests can mutate stores in place, so detach the saved state here.
            snapshot = deepcopy(getattr(restore_state, f"snapshot_{store}_session_state")())
            cleanup.callback(getattr(restore_state, f"restore_{store}_session_state"), snapshot)
        yield

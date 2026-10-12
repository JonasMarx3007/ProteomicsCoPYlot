"""The `/api/plots` router: every plot and plot-table route the pages call.

The routes live in one module per URL prefix (`plots_qc`, `plots_stats`, ...)
and share their error contract and response shapes through `plot_responses`.
This module combines them, so `app.main` includes one router and the URLs and
the OpenAPI document are what they were when everything was in one file.
"""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.api import (
    plots_comparison, plots_data, plots_peptide, plots_phospho, plots_qc, plots_single_protein, plots_stats,
)
from app.api.download_headers import attachment_disposition
from app.api.plot_responses import LOGGER

router = APIRouter(prefix="/api/plots", tags=["plots"])

# In the order the routes were declared before the split, which is the order
# they appear in the OpenAPI document.
ROUTE_MODULES = (plots_stats, plots_peptide, plots_data, plots_qc, plots_single_protein, plots_phospho, plots_comparison)


@router.get("/notebooks/{token}.zip")
def download_plot_notebook(token: str) -> Response:
    from app.services.notebook_snapshots import snapshots
    from app.services.notebook_archive import build_notebook_archive
    from app.services.session_context import get_session_id

    if len(token) != 32 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in token):
        raise HTTPException(status_code=404, detail="Notebook snapshot unavailable; render the plot again.")
    try:
        # The original-file replay is prepared here, on first download.
        recipe = snapshots.get(get_session_id(), token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook snapshot unavailable; render the plot again.") from exc
    except ValueError as exc:
        # Says what stands in the way (e.g. regenerate annotations, install R/vsn).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        filename, content = build_notebook_archive(recipe)
    except (ValueError, ModuleNotFoundError) as exc:
        LOGGER.exception("Could not build notebook export")
        raise HTTPException(status_code=409, detail="This notebook could not be packaged reproducibly. Render the plot again or contact the maintainer.") from exc
    return Response(content, media_type="application/zip", headers={
        "Content-Disposition": attachment_disposition(filename),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Encoding": "identity",  # a ZIP is compressed already
    })




for _module in ROUTE_MODULES:
    router.include_router(_module.router)

# Every route by name: what a test reaches for when it calls a route directly,
# checks its signature or its path. Built from the modules' own routers, since
# an included router may be held by reference rather than copied.
ROUTE_FUNCTIONS: dict[str, Callable] = {}
ROUTE_PATHS: dict[str, str] = {}
for _route in router.routes:
    if hasattr(_route, "endpoint"):
        ROUTE_FUNCTIONS[_route.endpoint.__name__] = _route.endpoint
        ROUTE_PATHS[_route.endpoint.__name__] = _route.path
for _module in ROUTE_MODULES:
    for _route in _module.router.routes:
        if hasattr(_route, "endpoint"):
            ROUTE_FUNCTIONS[_route.endpoint.__name__] = _route.endpoint
            ROUTE_PATHS[_route.endpoint.__name__] = router.prefix + _route.path

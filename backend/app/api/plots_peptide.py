from __future__ import annotations

"""Peptide-level plots: retention time, modifications, missed cleavages (`/api/plots/peptide/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.api.plot_responses import plot_errors, png_response

router = APIRouter()  # mounted under /api/plots by routes_plots


@router.get("/peptide/rt.png")
def peptide_rt_route(
    method: str = "Hexbin Plot",
    addLine: bool = False,
    bins: int = 1000,
    header: bool = True,
    randomSeed: int = 69,
    widthCm: float = 20,
    heightCm: float = 15,
    dpi: int = 100,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render peptide RT plot"):
        from app.services.notebook_peptide import render_rt
        content, token = render_rt(
            method=method,
            add_line=addLine,
            bins=bins,
            header=header,
            sampling_seed=randomSeed,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/peptide/rt-interactive.html", response_class=HTMLResponse)
def peptide_rt_interactive_route(
    addLine: bool = False,
    header: bool = True,
    randomSeed: int = 69,
    widthCm: float = 20,
    heightCm: float = 15,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive peptide RT plot", optional_dependency=True):
        from app.services.notebook_peptide import render_interactive_rt
        html, token = render_interactive_rt(
            add_line=addLine,
            header=header,
            sampling_seed=randomSeed,
            width_cm=widthCm,
            height_cm=heightCm,
            advanced=parse_advanced_plot_settings(advanced),
        )
        return HTMLResponse(content=html, headers={'X-CoPYlot-Notebook': token} if token else {})


@router.get("/peptide/modification.png")
def peptide_modification_route(
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 25,
    heightCm: float = 15,
    dpi: int = 100,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render peptide modification plot"):
        from app.services.notebook_peptide import render_modification
        content, token = render_modification(
            include_id=includeId,
            header=header,
            legend=legend,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/peptide/missed-cleavage.png")
def peptide_missed_cleavage_route(
    includeId: bool = False,
    text: bool = True,
    textSize: int = 8,
    header: bool = True,
    protease: str = "trypsin",
    widthCm: float = 25,
    heightCm: float = 15,
    dpi: int = 100,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render peptide missed-cleavage plot"):
        from app.services.notebook_peptide import render_missed_cleavage
        content, token = render_missed_cleavage(
            include_id=includeId, text=text, text_size=textSize, header=header,
            protease=protease, width_cm=widthCm, height_cm=heightCm, dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response

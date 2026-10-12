from __future__ import annotations

"""Pearson and Venn comparisons (`/api/plots/comparison/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from app.services.plot_export import note_notebook_unavailable
from app.schemas.annotation import AnnotationKind
from app.services.comparison_tools import (
    pearson_correlation_html,
    pearson_correlation_png,
    venn_png,
)
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.services.comparison_tools import (
    comparison_options,
    pearson_correlation_table,
    venn_table,
)
from app.api.plot_responses import plot_errors, png_response, snapshot_table, table_rows

router = APIRouter()  # mounted under /api/plots by routes_plots


@router.get("/comparison/{kind}/options")
def comparison_options_route(
    kind: AnnotationKind,
) -> dict[str, list[str] | dict[str, str] | int | bool | str]:
    with plot_errors("Failed to load comparison options"):
        return comparison_options(kind=kind)


def _comparison_notebook_response(plot, *, interactive=False, **options):
    from app.services.notebook_comparison import render_comparison
    from app.services.notebook_provenance import NotebookProvenanceError
    try:
        content, token = render_comparison(plot, interactive=interactive, **options)
    except NotebookProvenanceError as exc:
        note_notebook_unavailable(exc)
        renderer = venn_png if plot == 'venn' else pearson_correlation_html if interactive else pearson_correlation_png
        content, token = renderer(**options), ''
    response = HTMLResponse(content=content) if interactive else png_response(content)
    if token:
        response.headers['X-CoPYlot-Notebook'] = token
    return response


@router.get("/comparison/{kind}/pearson.png")
def comparison_pearson_route(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dotSize: float = 60,
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render Pearson correlation", optional_dependency=True):
        return _comparison_notebook_response('pearson',
                kind=kind,
                mode=mode,
                sample1=sample1,
                sample2=sample2,
                condition1=condition1,
                condition2=condition2,
                alias1=alias1,
                alias2=alias2,
                color=color,
                dot_size=dotSize,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/comparison/{kind}/pearson.html", response_class=HTMLResponse)
def comparison_pearson_interactive_route(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    color: str = "#1f77b4",
    dotSize: float = 8,
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 12,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive Pearson correlation", optional_dependency=True):
        return _comparison_notebook_response('pearson', interactive=True,
                kind=kind,
                mode=mode,
                sample1=sample1,
                sample2=sample2,
                condition1=condition1,
                condition2=condition2,
                alias1=alias1,
                alias2=alias2,
                color=color,
                dot_size=dotSize,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/comparison/{kind}/pearson-table")
def comparison_pearson_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
    snapshot: str = '',
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, 'comparison_pearson', snapshot, mode=mode,
            sample1=sample1, sample2=sample2, condition1=condition1, condition2=condition2,
            alias1=alias1, alias2=alias2)
    with plot_errors("Failed to load Pearson table"):
        return table_rows(
            pearson_correlation_table(
                kind=kind,
                mode=mode,
                sample1=sample1,
                sample2=sample2,
                condition1=condition1,
                condition2=condition2,
                alias1=alias1,
                alias2=alias2,
            )
        )


@router.get("/comparison/{kind}/venn.png")
def comparison_venn_route(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
    color1: str = "#1f77b4",
    color2: str = "#ff7f0e",
    color3: str = "#2ca02c",
    header: bool = True,
    widthCm: float = 15,
    heightCm: float = 12,
    dpi: int = 300,
    advanced: str = "",
    minPresent: int = 1,
) -> Response:
    with plot_errors("Failed to render Venn diagram", optional_dependency=True):
        return _comparison_notebook_response('venn',
                kind=kind,
                mode=mode,
                first=first,
                second=second,
                third=third,
                alias1=alias1,
                alias2=alias2,
                alias3=alias3,
                color1=color1,
                color2=color2,
                color3=color3,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
                min_present=minPresent,
        )


@router.get("/comparison/{kind}/venn-table")
def comparison_venn_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
    snapshot: str = '',
    minPresent: int = 1,
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, 'comparison_venn', snapshot, mode=mode,
            first=first, second=second, third=third, alias1=alias1, alias2=alias2, alias3=alias3,
            min_present=minPresent)
    with plot_errors("Failed to load Venn table"):
        return table_rows(
            venn_table(
                kind=kind,
                mode=mode,
                first=first,
                second=second,
                third=third,
                alias1=alias1,
                alias2=alias2,
                alias3=alias3,
                min_present=minPresent,
            )
        )

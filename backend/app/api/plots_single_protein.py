from __future__ import annotations

"""Single-protein boxplot, lineplot and heatmap (`/api/plots/single-protein/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from app.schemas.annotation import AnnotationKind, DataSource
from app.schemas.qc import FeatureIdentifier, SingleProteinTab
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.services.single_protein_tools import (
    single_protein_boxplot_plot,
    single_protein_heatmap_plot,
    single_protein_lineplot_plot,
)
from app.services.single_protein_tools import (
    single_protein_boxplot_table,
    single_protein_heatmap_table,
    single_protein_lineplot_table,
    single_protein_options,
    unmatched_lineplot_names,
    unmatched_names_notice,
)
from app.api.plot_responses import csv_values, plot_errors, png_response, snapshot_table, table_rows

router = APIRouter()  # mounted under /api/plots by routes_plots


@router.get("/single-protein/{kind}/options")
def single_protein_options_route(
    kind: AnnotationKind,
    tab: SingleProteinTab = "boxplot",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
) -> dict[str, object]:
    with plot_errors("Failed to load single-protein options"):
        return single_protein_options(
            kind=kind,
            tab=tab,
            identifier=identifier,
            data_source=dataSource,
        )


@router.get("/single-protein/{kind}/boxplot.png")
def single_protein_boxplot_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    outliers: bool = False,
    dots: bool = False,
    randomSeed: int = 69,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
    sampleN: bool = True,
) -> Response:
    with plot_errors("Failed to render single-protein boxplot", optional_dependency=True):
        options: dict[str, Any] = dict(
            kind=kind,
            protein=protein,
            conditions=csv_values(conditions),
            identifier=identifier,
            data_source=dataSource,
            outliers=outliers,
            dots=dots,
            sample_n=sampleN,
            random_seed=randomSeed,
            header=header,
            legend=legend,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        from app.services.notebook_single import render_box
        from app.services.notebook_provenance import NotebookProvenanceError
        try:
            content, token = render_box(**options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = png_response(single_protein_boxplot_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/single-protein/{kind}/lineplot.png")
def single_protein_lineplot_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
    showNaLow: bool = False,
) -> Response:
    with plot_errors("Failed to render single-protein lineplot", optional_dependency=True):
        options: dict[str, Any] = dict(
            kind=kind,
            proteins=csv_values(proteins),
            conditions=csv_values(conditions),
            include_id=includeId,
            show_na_low=showNaLow,
            identifier=identifier,
            data_source=dataSource,
            header=header,
            legend=legend,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        from app.services.notebook_single import render_line
        from app.services.notebook_provenance import NotebookProvenanceError
        from urllib.parse import quote, unquote
        try:
            content, token = render_line(**options)
        except NotebookProvenanceError as exc:
            response = png_response(single_protein_lineplot_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            token = ''
        else:
            response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        # Names that match no row are left out of the figure; say which, under it.
        missing = unmatched_names_notice(unmatched_lineplot_names(
            kind, options['proteins'], identifier=identifier, data_source=dataSource))
        if missing:
            earlier = unquote(response.headers.get('X-CoPYlot-Notice', ''))
            response.headers['X-CoPYlot-Notice'] = quote(f'{missing} {earlier}'.strip())
        return response


@router.get("/single-protein/{kind}/lineplot-unmatched")
def single_protein_lineplot_unmatched_route(
    kind: AnnotationKind,
    proteins: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
) -> dict[str, str]:
    """The notice the lineplot shows under itself, for pages that draw it as a plain image."""
    with plot_errors("Failed to check the lineplot selection"):
        return {"notice": unmatched_names_notice(unmatched_lineplot_names(
            kind, csv_values(proteins), identifier=identifier, data_source=dataSource))}


@router.get("/single-protein/{kind}/heatmap.png")
def single_protein_heatmap_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    includeId: bool = False,
    header: bool = True,
    filterM1: bool = True,
    clusterRows: bool = False,
    clusterCols: bool = False,
    valueType: str = "log2",
    cmap: str = "plasma",
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render single-protein heatmap", optional_dependency=True):
        options: dict[str, Any] = dict(
            kind=kind,
            protein=protein,
            conditions=csv_values(conditions),
            identifier=identifier,
            data_source=dataSource,
            include_id=includeId,
            header=header,
            filter_m1=filterM1,
            cluster_rows=clusterRows,
            cluster_cols=clusterCols,
            value_type=valueType,
            cmap_name=cmap,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )
        from app.services.notebook_single import render_heatmap
        from app.services.notebook_provenance import NotebookProvenanceError
        try:
            content, token = render_heatmap(**options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = png_response(single_protein_heatmap_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/single-protein/{kind}/boxplot-table")
def single_protein_boxplot_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, 'single_boxplot', snapshot, protein=protein,
            conditions=csv_values(conditions), identifier=identifier, data_source=dataSource)
    with plot_errors("Failed to load single-protein boxplot table"):
        return table_rows(
            single_protein_boxplot_table(
                kind=kind,
                protein=protein,
                conditions=csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
            )
        )


@router.get("/single-protein/{kind}/lineplot-table")
def single_protein_lineplot_table_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, 'single_lineplot', snapshot, proteins=csv_values(proteins),
            conditions=csv_values(conditions), include_id=includeId, identifier=identifier, data_source=dataSource)
    with plot_errors("Failed to load single-protein lineplot table"):
        return table_rows(
            single_protein_lineplot_table(
                kind=kind,
                proteins=csv_values(proteins),
                conditions=csv_values(conditions),
                include_id=includeId,
                identifier=identifier,
                data_source=dataSource,
            )
        )


@router.get("/single-protein/{kind}/heatmap-table")
def single_protein_heatmap_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: DataSource = "data",
    includeId: bool = False,
    filterM1: bool = True,
    clusterRows: bool = False,
    clusterCols: bool = False,
    valueType: str = "log2",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, 'single_heatmap', snapshot, protein=protein,
            conditions=csv_values(conditions), identifier=identifier, data_source=dataSource,
            include_id=includeId, filter_m1=filterM1, cluster_rows=clusterRows,
            cluster_cols=clusterCols, value_type=valueType)
    with plot_errors("Failed to load single-protein heatmap table", optional_dependency=True):
        return table_rows(
            single_protein_heatmap_table(
                kind=kind,
                protein=protein,
                conditions=csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
                include_id=includeId,
                filter_m1=filterM1,
                cluster_rows=clusterRows,
                cluster_cols=clusterCols,
                value_type=valueType,
            )
        )

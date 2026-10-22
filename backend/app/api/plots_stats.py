from __future__ import annotations

"""Volcano, ANOVA, ORA, pathway-heatmap and simulation plots (`/api/plots/stats/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""

from dataclasses import dataclass
from typing import Any, Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.services.plot_export import note_notebook_unavailable
from app.schemas.annotation import AnnotationKind, DataSource
from app.schemas.qc import FeatureIdentifier
from app.schemas.stats import (
    AnovaClusterMethod,
    AnovaRequest,
    AnovaResultResponse,
    EnrichmentOrganism,
    EnrichmentRequest,
    EnrichmentResultResponse,
    HeatmapValueType,
    OraDirection,
    SimulationRequest,
    SimulationTestType,
    StatsTestType,
    VolcanoControlRequest,
    VolcanoRequest,
)
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.services.functions import (
    parse_selection_list,
)
from app.services.stats_tools import (
    anova_png,
    ora_plot_png,
    pathway_heatmap_png,
    simulation_html,
    volcano_html,
    volcano_png,
)
from app.services.json_records import json_records
from app.api.plot_responses import plot_errors, png_response

router = APIRouter()  # mounted under /api/plots by routes_plots


def split_terms(value: str) -> list[str]:
    """A comma-separated highlight list as the model wants it."""
    return [term.strip() for term in value.split(",") if term.strip()]


@dataclass
class VolcanoQuery:
    """What a volcano is *of*: the comparison, the matrix and the test.

    The printed figure and the interactive page answer that question the same
    way and differ only in how they draw it, so both read it from here instead
    of repeating the list. The ORA pair drifted exactly that way once: the
    figure route lost `clusterMethod` and drew a different partition than the
    table beside it. Sharing the parameters makes that
    impossible rather than unlikely.
    """

    condition1: str
    condition2: str
    dataSource: DataSource = "data"
    identifier: FeatureIdentifier = "workflow"
    pValueThreshold: float = 0.05
    log2fcThreshold: float = 1.0
    testType: StatsTestType = "unpaired"
    useUncorrected: bool = False
    highlightTerms: str = ""
    proteinCorrection: bool = False

    def request(self, kind: AnnotationKind) -> VolcanoRequest:
        return VolcanoRequest(
            kind=kind,
            dataSource=self.dataSource,
            condition1=self.condition1,
            condition2=self.condition2,
            identifier=self.identifier,
            pValueThreshold=self.pValueThreshold,
            log2fcThreshold=self.log2fcThreshold,
            testType=self.testType,
            useUncorrected=self.useUncorrected,
            highlightTerms=split_terms(self.highlightTerms),
            proteinCorrection=self.proteinCorrection,
        )


@dataclass
class VolcanoControlQuery:
    """The same question, plus the two conditions the change is measured against."""

    volcano: Annotated[VolcanoQuery, Depends()]
    condition1Control: str
    condition2Control: str

    def request(self, kind: AnnotationKind) -> VolcanoControlRequest:
        base = self.volcano
        return VolcanoControlRequest(
            kind=kind,
            dataSource=base.dataSource,
            condition1=base.condition1,
            condition2=base.condition2,
            condition1Control=self.condition1Control,
            condition2Control=self.condition2Control,
            identifier=base.identifier,
            pValueThreshold=base.pValueThreshold,
            log2fcThreshold=base.log2fcThreshold,
            testType=base.testType,
            useUncorrected=base.useUncorrected,
            proteinCorrection=base.proteinCorrection,
            highlightTerms=split_terms(base.highlightTerms),
        )


@router.get("/stats/{kind}/volcano.html", response_class=HTMLResponse)
def stats_volcano_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoQuery, Depends()],
    highlightOutline: bool = True,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render volcano plot"):
        return _volcano_notebook_html(query.request(kind), advanced=parse_advanced_plot_settings(advanced),
                                      highlight_outline=highlightOutline)


@router.get("/stats/{kind}/volcano-control.html", response_class=HTMLResponse)
def stats_volcano_control_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoControlQuery, Depends()],
    highlightOutline: bool = True,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render control volcano plot"):
        return _volcano_notebook_html(query.request(kind), advanced=parse_advanced_plot_settings(advanced),
                                      highlight_outline=highlightOutline)


@router.get("/stats/{kind}/volcano.png")
def stats_volcano_png_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoQuery, Depends()],
    labelTopUp: int = 0,
    labelTopDown: int = 0,
    highlightOutline: bool = True,
    highlightLabels: bool = False,
    widthCm: float = 18,
    heightCm: float = 14,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    """The volcano as a figure for print. Same numbers, journal styling."""
    with plot_errors("Failed to render volcano plot"):
        return _volcano_notebook_png(
            query.request(kind),
            advanced=parse_advanced_plot_settings(advanced),
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            label_top_up=labelTopUp,
            label_top_down=labelTopDown,
            highlight_outline=highlightOutline,
            highlight_labels=highlightLabels,
        )


@router.get("/stats/{kind}/volcano-control.png")
def stats_volcano_control_png_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoControlQuery, Depends()],
    labelTopUp: int = 0,
    labelTopDown: int = 0,
    highlightOutline: bool = True,
    highlightLabels: bool = False,
    widthCm: float = 18,
    heightCm: float = 14,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render control volcano plot"):
        return _volcano_notebook_png(
            query.request(kind),
            advanced=parse_advanced_plot_settings(advanced),
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            label_top_up=labelTopUp,
            label_top_down=labelTopDown,
            highlight_outline=highlightOutline,
            highlight_labels=highlightLabels,
        )


def _volcano_notebook_html(payload, **options) -> HTMLResponse:
    from app.services.notebook_volcano import render_volcano
    from app.services.notebook_provenance import NotebookProvenanceError
    try:
        content, token = render_volcano(payload, interactive=True, **options)
    except NotebookProvenanceError as exc:
        note_notebook_unavailable(exc)
        return HTMLResponse(content=volcano_html(payload, **options))
    response = HTMLResponse(content=content)
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response


def _volcano_notebook_png(payload, **options) -> Response:
    from app.services.notebook_volcano import render_volcano
    from app.services.notebook_provenance import NotebookProvenanceError
    try:
        content, token = render_volcano(payload, **options)
    except NotebookProvenanceError as exc:
        from urllib.parse import quote
        response = png_response(volcano_png(payload, **options))
        response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
        return response
    response = png_response(content)
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response


@router.get("/stats/{kind}/volcano-table")
def stats_volcano_snapshot_table(kind: AnnotationKind, snapshot: str):
    import io
    import pandas as pd
    from app.services.notebook_snapshots import snapshots
    from app.services.session_context import get_session_id
    from app.services.stats_tools import _volcano_response
    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(404, "Notebook snapshot unavailable; render the volcano again.") from exc
    info = recipe.provenance
    if info.get("kind") != kind or info.get("plot") != "volcano":
        raise HTTPException(409, "The snapshot does not match this volcano dataset.")
    table = pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"]))
    untested = (pd.read_parquet(io.BytesIO(recipe.resources["untested.parquet"]))
                if "untested.parquet" in recipe.resources else None)
    return _volcano_response(kind, info["sourceUsed"], info["labelColumn"], table, info["warnings"], untested)


@router.get("/stats/{kind}/anova.png")
def stats_anova_route(
    kind: AnnotationKind,
    source: str = "anova",
    dataSource: str = "data",
    identifier: FeatureIdentifier = "workflow",
    pValueThreshold: float = 0.05,
    useUncorrected: bool = False,
    showDendrograms: bool = True,
    showLegend: bool = True,
    showRowLabels: bool = False,
    nClusters: int = 4,
    clusterMethod: AnovaClusterMethod = "average",
    selectedCluster: int | None = None,
    postHoc: str = "none",
    postHocCondition1: str | None = None,
    postHocCondition2: str | None = None,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render ANOVA plot"):
        payload = AnovaRequest.model_validate(dict(
            kind=kind,
            source=source,
            dataSource=dataSource,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            useUncorrected=useUncorrected,
            showDendrograms=showDendrograms,
            showLegend=showLegend,
            showRowLabels=showRowLabels,
            nClusters=nClusters,
            # The heatmap must cluster the same way the table did, or the plot
            # and the cluster column disagree about which rows are cluster 1.
            clusterMethod=clusterMethod,
            postHoc=postHoc,
            postHocCondition1=postHocCondition1,
            postHocCondition2=postHocCondition2,
        ))
        from app.services.notebook_anova import render_anova
        from app.services.notebook_provenance import NotebookProvenanceError
        options: dict[str, Any] = dict(selected_cluster=selectedCluster, advanced=parse_advanced_plot_settings(advanced))
        try:
            content, token = render_anova(payload, **options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = png_response(anova_png(payload, **options))
            response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
            return response
        response = png_response(content)
        if token:
            response.headers["X-CoPYlot-Notebook"] = token
        return response


@router.get("/stats/{kind}/anova-tables", response_model=AnovaResultResponse)
def stats_anova_snapshot_tables(kind: AnnotationKind, snapshot: str):
    import io
    import json
    import pandas as pd
    from app.services.notebook_snapshots import snapshots
    from app.services.session_context import get_session_id
    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(404, "Notebook snapshot unavailable; render the ANOVA again.") from exc
    if recipe.provenance.get("kind") != kind or recipe.provenance.get("plot") != "anova":
        raise HTTPException(409, "The snapshot does not match this ANOVA dataset.")
    result = json.loads(recipe.resources["summary.json"])
    for key in ("rows", "clusterRows", "postHocRows"):
        table = pd.read_parquet(io.BytesIO(recipe.resources[f"{key}.parquet"]))
        result[key] = json_records(table)
    return AnovaResultResponse(**result)


@router.get("/stats/{kind}/ora/{direction}.png")
def stats_ora_route(
    kind: AnnotationKind,
    direction: OraDirection,
    condition1: str = "",
    condition2: str = "",
    source: str = "volcano",
    dataSource: str = "data",
    condition1Control: str | None = None,
    condition2Control: str | None = None,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: StatsTestType = "unpaired",
    useUncorrected: bool = False,
    selectedCluster: int | None = None,
    nClusters: int = 4,
    adjPValueCutoff: float = 0.05,
    topN: int = 10,
    minTermSize: int = 20,
    maxTermSize: int = 300,
    backgroundMode: str = "experiment",
    clusterMethod: AnovaClusterMethod = "average",
    organism: str = "human",
    widthCm: float = 26,
    heightCm: float = 12,
    dpi: int = 300,
    tableOnly: bool = False,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render ORA plot"):
        payload = EnrichmentRequest.model_validate(dict(
            kind=kind,
            source=source,
            dataSource=dataSource,
            # Must reach the request: an ANOVA-cluster ORA re-runs the clustering,
            # and a dropped linkage draws "cluster n" from a different partition
            # than the table the user is looking at.
            clusterMethod=clusterMethod,
            organism=organism,
            condition1=condition1,
            condition2=condition2,
            condition1Control=condition1Control,
            condition2Control=condition2Control,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            selectedCluster=selectedCluster,
            nClusters=nClusters,
            adjPValueCutoff=adjPValueCutoff,
            topN=topN,
            minTermSize=minTermSize,
            maxTermSize=maxTermSize,
            backgroundMode=backgroundMode,
        ))
        from app.services.notebook_ora import render_ora
        from app.services.notebook_provenance import NotebookProvenanceError
        options: dict[str, Any] = dict(direction=direction, advanced=parse_advanced_plot_settings(advanced),
                       width_cm=widthCm, height_cm=heightCm, dpi=dpi)
        try:
            content, token = render_ora(payload, table_only=tableOnly, **options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = Response() if tableOnly else png_response(ora_plot_png(payload, **options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = Response() if tableOnly else png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get('/stats/{kind}/ora/{direction}/tables', response_model=EnrichmentResultResponse)
def stats_ora_snapshot_tables(kind: AnnotationKind, direction: OraDirection, snapshot: str):
    import json
    from app.services.notebook_snapshots import snapshots
    from app.services.session_context import get_session_id
    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(404, 'Notebook snapshot unavailable; render ORA again.') from exc
    info = recipe.provenance
    if info.get('kind') != kind or info.get('plot') != 'ora' or info.get('direction') != direction:
        raise HTTPException(409, 'The snapshot does not match this ORA plot.')
    return EnrichmentResultResponse(**json.loads(recipe.resources['result.json']))


@router.get("/stats/{kind}/pathway-heatmap.png")
def stats_pathway_heatmap_route(
    kind: AnnotationKind,
    pathway: str,
    dataSource: str = "data",
    conditions: str = "",
    valueType: HeatmapValueType = "z",
    includeId: bool = True,
    header: bool = True,
    removeEmpty: bool = True,
    clusterRows: bool = False,
    clusterCols: bool = False,
    showSourceCount: bool = False,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 300,
    advanced: str = "",
    organism: EnrichmentOrganism = "human",
) -> Response:
    with plot_errors("Failed to render pathway heatmap"):
        condition_list = parse_selection_list(conditions)
        options: dict[str, Any] = dict(
            kind=kind,
            pathway=pathway,
            organism=organism,
            conditions=condition_list,
            value_type=valueType,
            include_id=includeId,
            header=header,
            remove_empty=removeEmpty,
            cluster_rows=clusterRows,
            cluster_cols=clusterCols,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            data_source=dataSource,
            show_source_count=showSourceCount,
            advanced=parse_advanced_plot_settings(advanced),
        )
        from app.services.notebook_pathway import render_pathway
        from app.services.notebook_provenance import NotebookProvenanceError
        try:
            content, token = render_pathway(**options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = png_response(pathway_heatmap_png(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/stats/{kind}/simulation.html", response_class=HTMLResponse)
def stats_simulation_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    dataSource: str = "data",
    identifier: FeatureIdentifier = "workflow",
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: SimulationTestType = "unpaired",
    useUncorrected: bool = False,
    varianceMultiplier: float = 1.0,
    sampleSizeOverride: int = 0,
    proteinCorrection: bool = False,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render simulation plot"):
        payload = SimulationRequest.model_validate(dict(
            kind=kind,
            source="volcano",
            dataSource=dataSource,
            condition1=condition1,
            condition2=condition2,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            varianceMultiplier=varianceMultiplier,
            sampleSizeOverride=sampleSizeOverride,
            proteinCorrection=proteinCorrection,
        ))
        return HTMLResponse(content=simulation_html(payload, advanced=parse_advanced_plot_settings(advanced)))

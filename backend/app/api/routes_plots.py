from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.services.plot_export import note_notebook_unavailable, RENDER_LOCK
from app.schemas.annotation import AnnotationKind, DataSource
from app.schemas.dataset import CompletenessDatasetKind
from app.schemas.qc import (
    BoxplotMode,
    FeatureIdentifier,
    FeatureScaling,
    PcaColorBy,
    PhosphoCoverageMode,
    PlotDimension,
    SingleProteinTab,
)
from app.schemas.stats import (
    AnovaClusterMethod,
    AnovaRequest,
    AnovaResultResponse,
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
from app.services.annotation_store import get_annotation
from app.services.comparison_tools import (
    pearson_correlation_html,
    pearson_correlation_png,
    venn_png,
)
from app.services.completeness_tools import (
    completeness_missing_value_heatmap,
    completeness_missing_value_plot,
)
from app.services.plot_images import (
    distribution_qqnorm_plot,
    imputation_after_plot,
    imputation_before_plot,
    imputation_overall_fit_plot,
    qc_abundance_interactive_html,
    qc_abundance_plot,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_interactive_html,
    qc_pca_plot,
)
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.services.single_protein_tools import (
    single_protein_boxplot_plot,
    single_protein_heatmap_plot,
    single_protein_lineplot_plot,
)
from app.services.functions import (
    _phosprot_values_are_centred,
    data_source_options,
    parse_selection_list,
    imputed_data_available,)
from app.services.single_protein_tools import (
    single_protein_boxplot_table,
    single_protein_heatmap_table,
    single_protein_lineplot_table,
    single_protein_options,
    unmatched_lineplot_names,
    unmatched_names_notice,
)
from app.services.comparison_tools import (
    comparison_options,
    pearson_correlation_table,
    venn_table,
)
from app.services.phospho_tools import (
    ksea_uploaded_volcano_html,
    ksea_table,
    phosprot_regulation_html,
    phosprot_regulation_table,
    phospho_coverage_table,
    phospho_distribution_table,
    phospho_options,
    phospho_sty_table,
    phosphosite_plot_table,
)
from app.services.dataset_reader import read_dataframe
from app.services.table_functions import (
    qc_boxplot_table,
    qc_coverage_table,
    qc_cv_table,
)
from app.services.stats_tools import (
    anova_png,
    ora_plot_png,
    pathway_heatmap_png,
    simulation_html,
    volcano_html,
    volcano_png,
)
from app.services.plot_images import (
    _sample_label,
    qc_pca_feature_summary,
)
from app.services.upload_limits import ensure_upload_size
from app.api.download_headers import attachment_disposition

LOGGER = logging.getLogger(__name__)


@contextmanager
def plot_errors(what: str, *, optional_dependency: bool = False):
    """Turn a renderer's failure into the answer the page expects.

    A `ValueError` is the renderer refusing the request -- an empty selection, a
    threshold out of range, a comparison that cannot be formed -- so its message
    *is* the answer and goes out as a 400. Anything else is ours to fix: it is
    logged with its traceback and answered with one fixed sentence, because an
    exception string can carry a file path or a column of someone's data.

    `optional_dependency` marks the plots that need a package the base install
    may not have. Those services raise `ModuleNotFoundError` with a message that
    names the package and how to install it, which is actionable and discloses
    nothing about the host, so that one message is passed through.

    Fifty-nine routes wrote these six lines out by hand.
    """
    try:
        # Plots are drawn one at a time (see RENDER_LOCK).
        with RENDER_LOCK:
            yield
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        if optional_dependency:
            LOGGER.exception("Optional dependency missing")
            raise HTTPException(status_code=500, detail=str(e)) from e
        LOGGER.exception(what)
        raise HTTPException(status_code=500, detail=f"{what}.") from e
    except Exception as e:
        LOGGER.exception(what)
        raise HTTPException(status_code=500, detail=f"{what}.") from e


router = APIRouter(prefix="/api/plots", tags=["plots"])


@router.get("/notebooks/{token}.zip")
def download_plot_notebook(token: str) -> Response:
    from app.services.notebook_qc import snapshots
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
    })


def _plot_media_type(content: bytes) -> str:
    """Name the format the renderer actually wrote, rather than assuming PNG.

    PDF and SVG are produced by matplotlib itself when the request asks for
    them, so the body arriving here is not always a raster. Serving an SVG as
    ``image/png`` makes the browser save a file it then refuses to open.
    """
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content[:64].lstrip().startswith((b"<?xml", b"<svg")):
        return "image/svg+xml"
    return "image/png"


def _png_response(content: bytes) -> Response:
    from urllib.parse import quote

    notice = getattr(content, "notice", "")
    return Response(
        content=content,
        media_type=_plot_media_type(content),
        headers={
            **({"X-CoPYlot-Notice": quote(notice)} if notice else {}),
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _table_rows(df) -> dict[str, list[dict[str, object]]]:
    # Categorical columns reject replacement values that are not registered
    # categories (including the empty string). Convert to ordinary Python
    # objects before replacing missing values for JSON serialization.
    safe_df = df.astype(object).where(df.notna(), "")
    return {"rows": safe_df.to_dict(orient="records")}



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
    table beside it (FABLE-REVIEW D2). Sharing the parameters makes that
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
            highlightTerms=split_terms(base.highlightTerms),
        )


@router.get("/stats/{kind}/volcano.html", response_class=HTMLResponse)
def stats_volcano_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoQuery, Depends()],
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render volcano plot"):
        return _volcano_notebook_html(query.request(kind), advanced=parse_advanced_plot_settings(advanced))


@router.get("/stats/{kind}/volcano-control.html", response_class=HTMLResponse)
def stats_volcano_control_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoControlQuery, Depends()],
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render control volcano plot"):
        return _volcano_notebook_html(query.request(kind), advanced=parse_advanced_plot_settings(advanced))


@router.get("/stats/{kind}/volcano.png")
def stats_volcano_png_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoQuery, Depends()],
    labelTopUp: int = 0,
    labelTopDown: int = 0,
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
        )


@router.get("/stats/{kind}/volcano-control.png")
def stats_volcano_control_png_route(
    kind: AnnotationKind,
    query: Annotated[VolcanoControlQuery, Depends()],
    labelTopUp: int = 0,
    labelTopDown: int = 0,
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
        response = _png_response(volcano_png(payload, **options))
        response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
        return response
    response = _png_response(content)
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response


@router.get("/stats/{kind}/volcano-table")
def stats_volcano_snapshot_table(kind: AnnotationKind, snapshot: str):
    import io
    import pandas as pd
    from app.services.notebook_qc import snapshots
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
        payload = AnovaRequest(
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
        )
        from app.services.notebook_anova import render_anova
        from app.services.notebook_provenance import NotebookProvenanceError
        options = dict(selected_cluster=selectedCluster, advanced=parse_advanced_plot_settings(advanced))
        try:
            content, token = render_anova(payload, **options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = _png_response(anova_png(payload, **options))
            response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
            return response
        response = _png_response(content)
        if token:
            response.headers["X-CoPYlot-Notebook"] = token
        return response


@router.get("/stats/{kind}/anova-tables", response_model=AnovaResultResponse)
def stats_anova_snapshot_tables(kind: AnnotationKind, snapshot: str):
    import io
    import json
    import pandas as pd
    from app.services.notebook_qc import snapshots
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
        result[key] = table.astype(object).where(pd.notna(table), None).to_dict(orient="records")
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
        payload = EnrichmentRequest(
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
        )
        from app.services.notebook_ora import render_ora
        from app.services.notebook_provenance import NotebookProvenanceError
        options = dict(direction=direction, advanced=parse_advanced_plot_settings(advanced),
                       width_cm=widthCm, height_cm=heightCm, dpi=dpi)
        try:
            content, token = render_ora(payload, table_only=tableOnly, **options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = Response() if tableOnly else _png_response(ora_plot_png(payload, **options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = Response() if tableOnly else _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get('/stats/{kind}/ora/{direction}/tables', response_model=EnrichmentResultResponse)
def stats_ora_snapshot_tables(kind: AnnotationKind, direction: OraDirection, snapshot: str):
    import json
    from app.services.notebook_qc import snapshots
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
) -> Response:
    with plot_errors("Failed to render pathway heatmap"):
        condition_list = parse_selection_list(conditions)
        options = dict(
            kind=kind,
            pathway=pathway,
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
            response = _png_response(pathway_heatmap_png(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = _png_response(content)
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
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render simulation plot"):
        payload = SimulationRequest(
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
        )
        return HTMLResponse(content=simulation_html(payload, advanced=parse_advanced_plot_settings(advanced)))


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
        response = _png_response(content)
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
        response = _png_response(content)
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
        response = _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


def _csv_values(raw: str) -> list[str]:
    return parse_selection_list(raw)


@router.get("/imputation/{kind}/before-missing.png")
def imputation_before_route(
    kind: AnnotationKind,
    method: str = "quantile",
    qValue: float = 0.01,
    adjustStd: float = 0.3,
    downShift: float = 1.8,
    width: float = 0.3,
    seed: int = 1337,
    sampleWise: bool = True,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render imputation plot"):
        return _png_response(
            imputation_before_plot(
                kind=kind,
                q_value=qValue,
                adjust_std=adjustStd,
                seed=seed,
                sample_wise=sampleWise,
                method=method,
                down_shift=downShift,
                width=width,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )


@router.get("/imputation/{kind}/overall-fit.png")
def imputation_overall_route(
    kind: AnnotationKind,
    method: str = "quantile",
    qValue: float = 0.01,
    adjustStd: float = 0.3,
    downShift: float = 1.8,
    width: float = 0.3,
    seed: int = 1337,
    sampleWise: bool = True,
    showImputationDraw: bool = True,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render imputation plot"):
        return _png_response(
            imputation_overall_fit_plot(
                kind=kind,
                q_value=qValue,
                adjust_std=adjustStd,
                seed=seed,
                sample_wise=sampleWise,
                show_imputation_draw=showImputationDraw,
                method=method,
                down_shift=downShift,
                width=width,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )


@router.get("/imputation/{kind}/after-imputation.png")
def imputation_after_route(
    kind: AnnotationKind,
    method: str = "quantile",
    qValue: float = 0.01,
    adjustStd: float = 0.3,
    downShift: float = 1.8,
    width: float = 0.3,
    seed: int = 1337,
    sampleWise: bool = True,
    normalization: str = "separate",
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render imputation plot"):
        return _png_response(
            imputation_after_plot(
                kind=kind,
                q_value=qValue,
                adjust_std=adjustStd,
                seed=seed,
                sample_wise=sampleWise,
                normalization=normalization,
                method=method,
                down_shift=downShift,
                width=width,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )


@router.get("/distribution/{kind}/qqnorm.png")
def distribution_qq_route(
    kind: AnnotationKind,
    randomSeed: int = 187,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QQ plot"):
        return _png_response(
            distribution_qqnorm_plot(
                kind,
                random_seed=randomSeed,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )


@router.get("/completeness/{kind}/missing-value.png")
def completeness_missing_value_route(
    kind: CompletenessDatasetKind,
    binCount: int = 0,
    header: bool = True,
    text: bool = True,
    textSize: int = 8,
    color: str = "#2563eb",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
    quantityColumn: str = "",
    tableIncludeId: bool = True,
    outlierThreshold: float = Query(default=50.0, ge=0, le=100),
) -> Response:
    with plot_errors("Failed to render completeness plot"):
        kind_normalized = kind.strip().lower()
        advanced_settings = parse_advanced_plot_settings(advanced)
        if kind_normalized in {"peptide", "precursor"}:
            from app.services.notebook_completeness import render_peptide_missing_values
            content, token = render_peptide_missing_values(
                kind_normalized, bin_count=binCount, header=header, text=text, text_size=textSize,
                color=color, width_cm=widthCm, height_cm=heightCm, dpi=dpi,
                advanced=advanced_settings, quantity_column=quantityColumn or None)
            response = _png_response(content)
            if token:
                response.headers["X-CoPYlot-Notebook"] = token
            return response
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            return _completeness_notebook_plot(
                "missing-value",
                table_include_id=tableIncludeId,
                outlier_threshold=outlierThreshold,
                kind=kind_normalized,
                bin_count=binCount,
                header=header,
                text=text,
                text_size=textSize,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=advanced_settings,
            )
        raise ValueError("Unsupported completeness dataset level.")


@router.get("/completeness/{kind}/missing-heatmap.png")
def completeness_missing_heatmap_route(
    kind: AnnotationKind,
    includeId: bool = True,
    header: bool = True,
    widthCm: float = 10,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
    tableIncludeId: bool = True,
    outlierThreshold: float = Query(default=50.0, ge=0, le=100),
) -> Response:
    with plot_errors("Failed to render completeness plot"):
        return _completeness_notebook_plot(
            "missing-heatmap",
            table_include_id=tableIncludeId,
            outlier_threshold=outlierThreshold,
            kind=kind,
            include_id=includeId,
            header=header,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )


def _completeness_notebook_plot(plot: str, *, kind: str, table_include_id: bool, outlier_threshold: float, **options) -> Response:
    from app.services.notebook_completeness import render_completeness
    from app.services.notebook_provenance import NotebookProvenanceError

    try:
        content, token = render_completeness(kind, plot=plot, table_include_id=table_include_id,
                                             outlier_threshold=outlier_threshold, **options)
    except NotebookProvenanceError as exc:
        from urllib.parse import quote
        renderer = completeness_missing_value_plot if plot == "missing-value" else completeness_missing_value_heatmap
        response = _png_response(renderer(kind=kind, **options))
        response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
        return response
    response = _png_response(content)
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response


@router.get("/qc/{kind}/coverage.png")
def qc_coverage_route(
    kind: CompletenessDatasetKind,
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    textSize: int = 9,
    randomSeed: int = 187,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
    quantityColumn: str = "",
    referenceLine: bool = True,
) -> Response:
    with plot_errors("Failed to render QC plot"):
        kind_normalized = kind.strip().lower()
        advanced_settings = parse_advanced_plot_settings(advanced)
        if kind_normalized in {"peptide", "precursor"}:
            from app.services.notebook_peptide import render_coverage
            content, token = render_coverage(
                include_id=includeId, header=header, legend=legend,
                width_cm=widthCm, height_cm=heightCm, dpi=dpi,
                advanced=advanced_settings, quantity_column=quantityColumn or None,
                level=kind_normalized, reference_line=referenceLine,
            )
            response = _png_response(content)
            if token:
                response.headers["X-CoPYlot-Notebook"] = token
            return response
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            return _qc_paired_plot(
                "coverage", kind=kind_normalized,
                include_id=includeId, header=header, legend=legend,
                summary=summary, text=text, text_size=textSize, random_seed=randomSeed,
                width_cm=widthCm, height_cm=heightCm, dpi=dpi,
                advanced=advanced_settings, reference_line=referenceLine,
            )
        raise ValueError("Unsupported QC dataset level.")


def _qc_snapshot_table(kind: str, plot: str, snapshot: str, **settings):
    import io
    import pandas as pd
    from app.services.notebook_qc import snapshots
    from app.services.session_context import get_session_id

    try:
        recipe = snapshots.peek(get_session_id(), snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Notebook snapshot unavailable; render the plot again.") from exc
    if (recipe.provenance.get("kind") != kind or recipe.provenance.get("plot") != plot
            or any(recipe.settings.get(key) != value for key, value in settings.items())):
        raise HTTPException(status_code=409, detail="The table settings do not match the rendered plot.")
    if 'table.json' in recipe.resources:
        import json
        return {'rows': json.loads(recipe.resources['table.json'])}
    return _table_rows(pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"])))


def _qc_paired_plot(plot: str, *, kind: str, **options) -> Response:
    renderer = {"coverage": qc_coverage_plot, "boxplot": qc_boxplot_plot, "cv": qc_cv_plot,
                "histogram": qc_intensity_histogram_plot, "abundance": qc_abundance_plot,
                "correlation": qc_correlation_plot, "pca": qc_pca_plot}[plot]
    eligible = kind in {"protein", "phospho", "phosprot"}
    if eligible:
        from app.services.notebook_qc import render_qc
        from app.services.notebook_provenance import NotebookProvenanceError
        try:
            if plot == "pca":
                from app.services.notebook_pca import render_pca
                content, token = render_pca(kind, **options)
            else:
                content, token = render_qc(kind, plot=plot, **options)
        except NotebookProvenanceError as exc:
            from urllib.parse import quote
            response = _png_response(renderer(kind=kind, **options))
            response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
            return response
        response = _png_response(content)
        if token:
            response.headers["X-CoPYlot-Notebook"] = token
        return response
    return _png_response(renderer(kind=kind, **options))


@router.get("/qc/{kind}/coverage-table")
def qc_coverage_table_route(
    kind: AnnotationKind,
    summary: bool = False,
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table(kind, "coverage", snapshot, summary=summary)
    with plot_errors("Failed to load coverage table"):
        return _table_rows(qc_coverage_table(kind=kind, summary=summary))


@router.get("/qc/{kind}/pca-features")
def qc_pca_features_route(
    kind: AnnotationKind,
    dataSource: str = "data",
    plotDim: PlotDimension = "2D",
    addEllipses: bool = False,
    method: str = "PCA",
    scaling: FeatureScaling = "auto",
    colorBy: PcaColorBy = "Condition",
    clusterMethod: str = "None",
    clusterCount: int = 3,
    dbscanEpsFactor: float = 0.5,
    dbscanMinSamples: int = 2,
    umapNNeighbors: int = 15,
    umapMinDist: float = 0.1,
    tsnePerplexity: float = 30.0,
    tsneLearningRate: float = 200.0,
    randomState: int = 42,
) -> dict[str, object]:
    # The ellipse notice needs the same projection the figure was drawn from, so
    # this route takes every control that moves a point.
    with plot_errors("Failed to summarise PCA features"):
        return qc_pca_feature_summary(
            kind,
            data_source=dataSource,
            plot_dim=plotDim,
            add_ellipses=addEllipses,
            method=method,
            scaling=scaling,
            color_by=colorBy,
            cluster_method=clusterMethod,
            cluster_count=clusterCount,
            dbscan_eps_factor=dbscanEpsFactor,
            dbscan_min_samples=dbscanMinSamples,
            umap_n_neighbors=umapNNeighbors,
            umap_min_dist=umapMinDist,
            tsne_perplexity=tsnePerplexity,
            tsne_learning_rate=tsneLearningRate,
            random_state=randomState,
        )


@router.get("/qc/{kind}/options")
def qc_options_route(kind: AnnotationKind) -> dict[str, object]:
    annotation = get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        return {
            "conditions": [],
            "samples": [],
            "sampleLabels": {},
            "sampleLabelsWithId": {},
            "imputedAvailable": False,
            "availableDataSources": [],
            "defaultDataSource": "data",
            "centredPhosprotValues": False,
        }
    conditions = [
        str(value)
        for value in annotation.metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
    ]
    samples = [
        str(value)
        for value in annotation.metadata["sample"].dropna().astype(str).drop_duplicates().tolist()
    ] if "sample" in annotation.metadata.columns else []
    sample_labels: dict[str, str] = {}
    sample_labels_with_id: dict[str, str] = {}
    if "sample" in annotation.metadata.columns and "condition" in annotation.metadata.columns:
        meta = annotation.metadata[["sample", "condition"]].dropna().copy()
        meta["sample"] = meta["sample"].astype(str)
        meta["condition"] = meta["condition"].astype(str)
        meta = meta.drop_duplicates(subset=["sample"], keep="first")
        meta["sample_index"] = meta.groupby("condition").cumcount()
        for row in meta.itertuples(index=False):
            sample = str(row.sample)
            condition = str(row.condition)
            index = int(row.sample_index)
            sample_labels[sample] = _sample_label(sample, condition, index, include_id=False)
            sample_labels_with_id[sample] = _sample_label(sample, condition, index, include_id=True).replace("\n", " ")
    return {
        "conditions": conditions,
        "samples": samples,
        "sampleLabels": sample_labels,
        "sampleLabelsWithId": sample_labels_with_id,
        "imputedAvailable": imputed_data_available(kind),
        # A `robust_site_median` collapse stores ratios to each site's own
        # median, not abundances. Only the backend knows how the phosphoprotein
        # frame was produced, so it says so here and the page warns under the
        # CV plot, whose numbers are not comparable with the other levels'.
        "centredPhosprotValues": _phosprot_values_are_centred(kind),
        # The PCA is the one plot on this page that chooses its matrix, so the
        # ladder is served here rather than worked out in the browser.
        **data_source_options(kind),
    }


@router.get("/qc/{kind}/intensity-histogram.png")
def qc_hist_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        return _qc_paired_plot(
            "histogram",
            kind=kind,
            header=header,
            legend=legend,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/qc/{kind}/boxplot.png")
def qc_boxplot_route(
    kind: AnnotationKind,
    mode: BoxplotMode = "Mean",
    outliers: bool = False,
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    textSize: int = 9,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        advanced_settings = parse_advanced_plot_settings(advanced)
        return _qc_paired_plot(
            "boxplot",
            kind=kind,
            mode=mode,
            outliers=outliers,
            include_id=includeId,
            header=header,
            legend=legend,
            text=text,
            text_size=textSize,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=advanced_settings,
        )


@router.get("/qc/{kind}/boxplot-table")
def qc_boxplot_table_route(
    kind: AnnotationKind,
    mode: BoxplotMode = "Mean",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table(kind, "boxplot", snapshot, mode=mode)
    with plot_errors("Failed to load boxplot table"):
        return _table_rows(qc_boxplot_table(kind=kind, mode=mode))


@router.get("/qc/{kind}/cv.png")
def qc_cv_route(
    kind: AnnotationKind,
    outliers: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    textSize: int = 9,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        return _qc_paired_plot(
            "cv",
            kind=kind,
            outliers=outliers,
            header=header,
            legend=legend,
            text=text,
            text_size=textSize,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/qc/{kind}/cv-table")
def qc_cv_table_route(kind: AnnotationKind, snapshot: str = "") -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table(kind, "cv", snapshot)
    with plot_errors("Failed to load CV table"):
        return _table_rows(qc_cv_table(kind=kind))


@router.get("/qc/{kind}/pca.png")
def qc_pca_route(
    kind: AnnotationKind,
    dataSource: str = "data",
    header: bool = True,
    legend: bool = True,
    plotDim: PlotDimension = "2D",
    method: str = "PCA",
    addEllipses: bool = False,
    dotSize: int = 5,
    clusterMethod: str = "None",
    clusterCount: int = 3,
    colorBy: PcaColorBy = "Condition",
    umapNNeighbors: int = 15,
    umapMinDist: float = 0.1,
    tsnePerplexity: float = 30.0,
    tsneLearningRate: float = 200.0,
    dbscanEpsFactor: float = 0.5,
    dbscanMinSamples: int = 2,
    randomState: int = 42,
    scaling: FeatureScaling = "auto",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        advanced_settings = parse_advanced_plot_settings(advanced)
        return _qc_paired_plot(
            "pca",
            kind=kind,
            data_source=dataSource,
            header=header,
            legend=legend,
            plot_dim=plotDim,
            method=method,
            add_ellipses=addEllipses,
            dot_size=dotSize,
            cluster_method=clusterMethod,
            cluster_count=clusterCount,
            color_by=colorBy,
            umap_n_neighbors=umapNNeighbors,
            umap_min_dist=umapMinDist,
            tsne_perplexity=tsnePerplexity,
            tsne_learning_rate=tsneLearningRate,
            dbscan_eps_factor=dbscanEpsFactor,
            dbscan_min_samples=dbscanMinSamples,
            random_state=randomState,
            scaling=scaling,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=advanced_settings,
        )


@router.get("/qc/{kind}/pca-interactive.html")
def qc_pca_interactive_route(
    kind: AnnotationKind,
    dataSource: str = "data",
    header: bool = True,
    legend: bool = True,
    plotDim: PlotDimension = "2D",
    method: str = "PCA",
    addEllipses: bool = False,
    dotSize: int = 8,
    clusterMethod: str = "None",
    clusterCount: int = 3,
    colorBy: PcaColorBy = "Condition",
    umapNNeighbors: int = 15,
    umapMinDist: float = 0.1,
    tsnePerplexity: float = 30.0,
    tsneLearningRate: float = 200.0,
    dbscanEpsFactor: float = 0.5,
    dbscanMinSamples: int = 2,
    randomState: int = 42,
    scaling: FeatureScaling = "auto",
    widthCm: float = 20,
    heightCm: float = 10,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive PCA plot", optional_dependency=True):
        options = dict(
            kind=kind,
            data_source=dataSource,
            header=header,
            legend=legend,
            plot_dim=plotDim,
            method=method,
            add_ellipses=addEllipses,
            dot_size=dotSize,
            cluster_method=clusterMethod,
            cluster_count=clusterCount,
            color_by=colorBy,
            umap_n_neighbors=umapNNeighbors,
            umap_min_dist=umapMinDist,
            tsne_perplexity=tsnePerplexity,
            tsne_learning_rate=tsneLearningRate,
            dbscan_eps_factor=dbscanEpsFactor,
            dbscan_min_samples=dbscanMinSamples,
            random_state=randomState,
            scaling=scaling,
            width_cm=widthCm,
            height_cm=heightCm,
            advanced=parse_advanced_plot_settings(advanced),
        )
        if kind in {"protein", "phospho", "phosprot"}:
            from app.services.notebook_pca import render_pca
            from app.services.notebook_provenance import NotebookProvenanceError
            try:
                html, token = render_pca(interactive=True, **options)
                return HTMLResponse(content=html, headers={"Cache-Control": "no-store", **({"X-CoPYlot-Notebook": token} if token else {})})
            except NotebookProvenanceError as exc:
                note_notebook_unavailable(exc)  # Keep the plot available even when an exact notebook cannot be documented.
        return HTMLResponse(content=qc_pca_interactive_html(**options))


@router.get("/qc/{kind}/abundance.png")
def qc_abundance_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        return _qc_paired_plot(
            "abundance",
            kind=kind,
            header=header,
            legend=legend,
            condition=condition,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/qc/{kind}/abundance-interactive.html")
def qc_abundance_interactive_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    widthCm: float = 20,
    heightCm: float = 10,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive abundance plot", optional_dependency=True):
        if kind in {"protein", "phospho", "phosprot"}:
            from app.services.notebook_interactive import render_abundance
            from app.services.notebook_provenance import NotebookProvenanceError
            try:
                html, token = render_abundance(kind, header=header, legend=legend, condition=condition,
                    width_cm=widthCm, height_cm=heightCm, advanced=parse_advanced_plot_settings(advanced))
                return HTMLResponse(content=html, headers={"Cache-Control": "no-store", **({"X-CoPYlot-Notebook": token} if token else {})})
            except NotebookProvenanceError as exc:
                note_notebook_unavailable(exc)
        html = qc_abundance_interactive_html(
            kind=kind,
            header=header,
            legend=legend,
            condition=condition,
            width_cm=widthCm,
            height_cm=heightCm,
            advanced=parse_advanced_plot_settings(advanced),
        )
        return HTMLResponse(content=html)


@router.get("/qc/{kind}/correlation.png")
def qc_correlation_route(
    kind: AnnotationKind,
    method: str = "Matrix",
    includeId: bool = False,
    fullRange: bool = False,
    widthCm: float = 20,
    heightCm: float = 16,
    dpi: int = 400,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render QC plot"):
        advanced_settings = parse_advanced_plot_settings(advanced)
        return _qc_paired_plot(
            "correlation",
            kind=kind,
            method=method,
            include_id=includeId,
            full_range=fullRange,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            advanced=advanced_settings,
        )


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
        options = dict(
            kind=kind,
            protein=protein,
            conditions=_csv_values(conditions),
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
            response = _png_response(single_protein_boxplot_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = _png_response(content)
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
        options = dict(
            kind=kind,
            proteins=_csv_values(proteins),
            conditions=_csv_values(conditions),
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
            response = _png_response(single_protein_lineplot_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            token = ''
        else:
            response = _png_response(content)
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
            kind, _csv_values(proteins), identifier=identifier, data_source=dataSource))}


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
        options = dict(
            kind=kind,
            protein=protein,
            conditions=_csv_values(conditions),
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
            response = _png_response(single_protein_heatmap_plot(**options))
            response.headers['X-CoPYlot-Notice'] = quote(f'Notebook export unavailable: {exc} The plot is unchanged.')
            return response
        response = _png_response(content)
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
        return _qc_snapshot_table(kind, 'single_boxplot', snapshot, protein=protein,
            conditions=_csv_values(conditions), identifier=identifier, data_source=dataSource)
    with plot_errors("Failed to load single-protein boxplot table"):
        return _table_rows(
            single_protein_boxplot_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
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
        return _qc_snapshot_table(kind, 'single_lineplot', snapshot, proteins=_csv_values(proteins),
            conditions=_csv_values(conditions), include_id=includeId, identifier=identifier, data_source=dataSource)
    with plot_errors("Failed to load single-protein lineplot table"):
        return _table_rows(
            single_protein_lineplot_table(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
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
        return _qc_snapshot_table(kind, 'single_heatmap', snapshot, protein=protein,
            conditions=_csv_values(conditions), identifier=identifier, data_source=dataSource,
            include_id=includeId, filter_m1=filterM1, cluster_rows=clusterRows,
            cluster_cols=clusterCols, value_type=valueType)
    with plot_errors("Failed to load single-protein heatmap table", optional_dependency=True):
        return _table_rows(
            single_protein_heatmap_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
                include_id=includeId,
                filter_m1=filterM1,
                cluster_rows=clusterRows,
                cluster_cols=clusterCols,
                value_type=valueType,
            )
        )


@router.get("/phospho/options")
def phospho_options_route() -> dict[str, object]:
    with plot_errors("Failed to load phospho options"):
        return phospho_options()


@router.get("/phospho/phosphosite-plot.png")
def phosphosite_plot_route(
    color: str = "#87CEEB",
    widthCm: float = 15,
    heightCm: float = 10,
    dpi: int = 100,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phosphosite plot", optional_dependency=True):
        from app.services.notebook_phospho import render_counts
        content, token = render_counts(color=color, width_cm=widthCm, height_cm=heightCm,
            dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/phosphosite-plot-table")
def phosphosite_plot_table_route(snapshot: str = '') -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table('phospho', 'phosphosite_counts', snapshot)
    with plot_errors("Failed to load phosphosite table"):
        return _table_rows(phosphosite_plot_table())


@router.get("/phospho/coverage.png")
def phospho_coverage_route(
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: PhosphoCoverageMode = "Normal",
    colorClassI: str = "#2563eb",
    colorNotClassI: str = "#f59e0b",
    randomSeed: int = 69,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    conditions: str = "",
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phospho coverage plot", optional_dependency=True):
        from app.services.notebook_phospho import render_coverage
        content, token = render_coverage(
            include_id=includeId,
            header=header,
            legend=legend,
            mode=mode,
            color_class_i=colorClassI,
            color_not_class_i=colorNotClassI,
            random_seed=randomSeed,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            conditions=_csv_values(conditions),
            advanced=parse_advanced_plot_settings(advanced),
        )
        response = _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/coverage-table")
def phospho_coverage_table_route(
    includeId: bool = False,
    mode: PhosphoCoverageMode = "Normal",
    conditions: str = "",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table('phospho', 'phosphosite_coverage', snapshot,
            include_id=includeId, mode=mode, conditions=_csv_values(conditions))
    with plot_errors("Failed to load phospho coverage table"):
        return _table_rows(
            phospho_coverage_table(
                include_id=includeId,
                mode=mode,
                conditions=_csv_values(conditions),
            )
        )


@router.get("/phospho/distribution.png")
def phospho_distribution_route(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    widthCm: float = 20,
    heightCm: float = 15,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phospho distribution plot", optional_dependency=True):
        from app.services.notebook_phospho import render_distribution
        content, token = render_distribution(cutoff=cutoff, header=header, color=color,
            width_cm=widthCm, height_cm=heightCm, dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/distribution-table")
def phospho_distribution_table_route(
    cutoff: float = 0.0,
    snapshot: str = '',
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table('phospho', 'phosphosite_distribution', snapshot, cutoff=cutoff)
    with plot_errors("Failed to load phospho distribution table"):
        return _table_rows(phospho_distribution_table(cutoff=cutoff))


@router.get("/phospho/ksea-table")
def phospho_ksea_table_route(
    condition1: str,
    condition2: str,
    source: str = "volcano",
    dataSource: str = "data",
    condition1Control: str | None = None,
    condition2Control: str | None = None,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    organism: str = "human",
) -> dict[str, object]:
    with plot_errors("Failed to load Kinase Library table"):
        from app.services.notebook_ksea import capture_table
        from app.services.notebook_provenance import NotebookProvenanceError
        options = dict(
                organism=organism,
                condition1=condition1,
                condition2=condition2,
                source=source,
                data_source=dataSource,
                condition1_control=condition1Control,
                condition2_control=condition2Control,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
        )
        try:
            table, token = capture_table(**options)
        except NotebookProvenanceError as exc:
            note_notebook_unavailable(exc)
            table, token = ksea_table(**options), ''
        return {**_table_rows(table), 'notebookToken': token or None}


@router.post("/phospho/ksea-volcano.html", response_class=HTMLResponse)
def phospho_ksea_uploaded_volcano_route(
    fileSt: UploadFile = File(...),
    fileTnc: UploadFile = File(...),
    pValueThreshold: float = Form(0.1),
    header: bool = Form(True),
    condition1: str = Form(""),
    condition2: str = Form(""),
    condition1Control: str = Form(""),
    condition2Control: str = Form(""),
    annotateHits: bool = Form(False),
    advanced: str = Form(""),
) -> HTMLResponse:
    if not fileSt.filename or not fileTnc.filename:
        raise HTTPException(status_code=400, detail="Both Kinase Library result files are required.")

    with plot_errors("Failed to generate Kinase Library volcano", optional_dependency=True):
        ensure_upload_size(fileSt, label="Kinase Library S/T result file")
        ensure_upload_size(fileTnc, label="Kinase Library Y result file")
        df_st = read_dataframe(fileSt.filename, fileSt.file)
        df_tnc = read_dataframe(fileTnc.filename, fileTnc.file)
        from app.services.assistant_snapshots import store_snapshot
        evidence = {}
        response = HTMLResponse(
            content=ksea_uploaded_volcano_html(
                st_results=df_st,
                evidence_out=evidence,
                tnc_results=df_tnc,
                p_value_threshold=pValueThreshold,
                header=header,
                condition1=condition1,
                condition2=condition2,
                condition1_control=condition1Control,
                condition2_control=condition2Control,
                annotate_hits=annotateHits,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
        response.headers["X-Copylot-Evidence"] = store_snapshot(evidence)
        return response


def _regulation_notebook_response(**options):
    from app.services.notebook_regulation import render_regulation
    from app.services.notebook_provenance import NotebookProvenanceError
    try:
        content, token = render_regulation(interactive=True, **options)
    except NotebookProvenanceError as exc:
        note_notebook_unavailable(exc)
        content, token = phosprot_regulation_html(**options), ''
    response = HTMLResponse(content=content)
    if token:
        response.headers['X-CoPYlot-Notebook'] = token
    return response


@router.get("/phospho/phosprot-regulation.html", response_class=HTMLResponse)
def phospho_phosprot_regulation_html_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    dataSource: DataSource = "data",
    header: bool = True,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive phosprot regulation plot", optional_dependency=True):
        return _regulation_notebook_response(
            condition1=condition1,
            condition2=condition2,
            p_value_threshold=pValueThreshold,
            log2fc_threshold=log2fcThreshold,
            test_type=testType,
            use_uncorrected=useUncorrected,
            max_hover_sites=maxHoverSites,
            show_phosphosites=showPhosphosites,
            data_source=dataSource,
            header=header,
            advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/phospho/phosprot-regulation-table")
def phospho_phosprot_regulation_table_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    dataSource: DataSource = "data",
    snapshot: str = '',
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table('phospho', 'phosprot_regulation', snapshot,
            condition1=condition1, condition2=condition2, p_value_threshold=pValueThreshold,
            log2fc_threshold=log2fcThreshold, test_type=testType, use_uncorrected=useUncorrected,
            max_hover_sites=maxHoverSites, show_phosphosites=showPhosphosites, data_source=dataSource)
    with plot_errors("Failed to load phosprot regulation table"):
        return _table_rows(
            phosprot_regulation_table(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                max_hover_sites=maxHoverSites,
                show_phosphosites=showPhosphosites,
                data_source=dataSource,
            )
        )


@router.get("/phospho/sty.png")
def phospho_sty_route(
    header: bool = True,
    widthCm: float = 17.78,
    heightCm: float = 11.43,
    dpi: int = 140,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render STY plot", optional_dependency=True):
        from app.services.notebook_phospho import render_sty
        content, token = render_sty(header=header, width_cm=widthCm, height_cm=heightCm,
            dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = _png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/sty-table")
def phospho_sty_table_route(snapshot: str = '') -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return _qc_snapshot_table('phospho', 'phosphosite_sty', snapshot)
    with plot_errors("Failed to load STY table"):
        return _table_rows(phospho_sty_table())


@router.get("/comparison/{kind}/options")
def comparison_options_route(
    kind: AnnotationKind,
) -> dict[str, list[str] | int | bool | str]:
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
    response = HTMLResponse(content=content) if interactive else _png_response(content)
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
        return _qc_snapshot_table(kind, 'comparison_pearson', snapshot, mode=mode,
            sample1=sample1, sample2=sample2, condition1=condition1, condition2=condition2,
            alias1=alias1, alias2=alias2)
    with plot_errors("Failed to load Pearson table"):
        return _table_rows(
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
        return _qc_snapshot_table(kind, 'comparison_venn', snapshot, mode=mode,
            first=first, second=second, third=third, alias1=alias1, alias2=alias2, alias3=alias3,
            min_present=minPresent)
    with plot_errors("Failed to load Venn table"):
        return _table_rows(
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

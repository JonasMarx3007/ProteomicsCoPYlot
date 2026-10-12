from __future__ import annotations

"""QC plots and their tables (`/api/plots/qc/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from typing import Any, Callable, cast

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from app.services.plot_export import note_notebook_unavailable
from app.schemas.annotation import AnnotationKind
from app.schemas.dataset import CompletenessDatasetKind
from app.schemas.qc import BoxplotMode, FeatureScaling, PcaColorBy, PlotDimension
from app.services.annotation_store import get_annotation
from app.services.plot_images import (
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
from app.services.analysis_matrix import phosprot_values_are_centred, data_source_options, imputed_data_available
from app.services.table_functions import (
    qc_boxplot_table,
    qc_coverage_table,
    qc_cv_table,
)
from app.services.plot_images import (
    _sample_label,
    qc_pca_feature_summary,
)
from app.api.plot_responses import plot_errors, png_response, snapshot_table, table_rows

router = APIRouter()  # mounted under /api/plots by routes_plots


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
            response = png_response(content)
            if token:
                response.headers["X-CoPYlot-Notebook"] = token
            return response
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            annotation_kind = cast(AnnotationKind, kind_normalized)
            return _qc_paired_plot(
                "coverage", kind=annotation_kind,
                include_id=includeId, header=header, legend=legend,
                summary=summary, text=text, text_size=textSize, random_seed=randomSeed,
                width_cm=widthCm, height_cm=heightCm, dpi=dpi,
                advanced=advanced_settings, reference_line=referenceLine,
            )
        raise ValueError("Unsupported QC dataset level.")


def _note_vsn_linear_qc(kind: AnnotationKind) -> None:
    """CV and abundance read unnormalized data after VSN; say so under the plot."""
    from app.services.data_tools import VSN_LINEAR_QC_NOTICE, linear_qc_uses_unnormalized
    from app.services.plot_export import note_plot_notice

    if linear_qc_uses_unnormalized(kind):
        note_plot_notice(VSN_LINEAR_QC_NOTICE)


def _qc_paired_plot(plot: str, *, kind: AnnotationKind, **options) -> Response:
    """The figure with its notebook token, or the figure alone when no notebook can be made."""
    renderers: dict[str, Callable[..., bytes]] = {"coverage": qc_coverage_plot, "boxplot": qc_boxplot_plot, "cv": qc_cv_plot,
                "histogram": qc_intensity_histogram_plot, "abundance": qc_abundance_plot,
                "correlation": qc_correlation_plot, "pca": qc_pca_plot}
    renderer = renderers[plot]
    if plot in {"cv", "abundance"}:
        _note_vsn_linear_qc(kind)
    from app.services.notebook_qc import render_qc
    from app.services.notebook_provenance import NotebookProvenanceError
    content: bytes | str
    try:
        if plot == "pca":
            from app.services.notebook_pca import render_pca
            content, token = render_pca(kind, **options)
        else:
            content, token = render_qc(kind, plot=plot, **options)
    except NotebookProvenanceError as exc:
        from urllib.parse import quote
        response = png_response(renderer(kind=kind, **options))
        response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
        return response
    response = png_response(content if isinstance(content, bytes) else content.encode())
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response


@router.get("/qc/{kind}/coverage-table")
def qc_coverage_table_route(
    kind: AnnotationKind,
    summary: bool = False,
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table(kind, "coverage", snapshot, summary=summary)
    with plot_errors("Failed to load coverage table"):
        return table_rows(qc_coverage_table(kind=kind, summary=summary))


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
        "centredPhosprotValues": phosprot_values_are_centred(kind),
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
        return snapshot_table(kind, "boxplot", snapshot, mode=mode)
    with plot_errors("Failed to load boxplot table"):
        return table_rows(qc_boxplot_table(kind=kind, mode=mode))


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
        return snapshot_table(kind, "cv", snapshot)
    with plot_errors("Failed to load CV table"):
        return table_rows(qc_cv_table(kind=kind))


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
        options: dict[str, Any] = dict(
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
        _note_vsn_linear_qc(kind)
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

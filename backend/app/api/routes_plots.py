from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import (
    EnrichmentRequest,
    SimulationRequest,
    VolcanoControlRequest,
    VolcanoRequest,
)
from app.services.annotation_store import get_annotation
from app.services.functions import (
    completeness_missing_value_heatmap,
    completeness_missing_value_plot,
    distribution_qqnorm_plot,
    imputation_after_plot,
    imputation_before_plot,
    imputation_overall_fit_plot,
    qc_abundance_plot,
    qc_abundance_interactive_html,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_plot,
    qc_pca_interactive_html,
    verification_duplicate_pattern_plot,
    verification_first_digit_plot,
)
from app.services.table_functions import (
    qc_boxplot_table,
    qc_coverage_table,
    qc_cv_table,
)
from app.services.stats_tools import (
    gsea_plot_png,
    pathway_heatmap_png,
    simulation_html,
    volcano_control_html,
    volcano_html,
)
from app.services.peptide_tools import (
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_plot,
)

router = APIRouter(prefix="/api/plots", tags=["plots"])


def _png_response(content: bytes) -> Response:
    return Response(content=content, media_type="image/png")


def _table_rows(df) -> dict[str, list[dict[str, object]]]:
    safe_df = df.fillna("")
    return {"rows": safe_df.to_dict(orient="records")}


@router.get("/stats/{kind}/volcano.html", response_class=HTMLResponse)
async def stats_volcano_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    identifier: str = "workflow",
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    highlightTerms: str = "",
) -> HTMLResponse:
    try:
        payload = VolcanoRequest(
            kind=kind,
            condition1=condition1,
            condition2=condition2,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            highlightTerms=[term.strip() for term in highlightTerms.split(",") if term.strip()],
        )
        return HTMLResponse(content=volcano_html(payload))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render volcano plot: {e}") from e


@router.get("/stats/{kind}/volcano-control.html", response_class=HTMLResponse)
async def stats_volcano_control_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    condition1Control: str,
    condition2Control: str,
    identifier: str = "workflow",
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    highlightTerms: str = "",
) -> HTMLResponse:
    try:
        payload = VolcanoControlRequest(
            kind=kind,
            condition1=condition1,
            condition2=condition2,
            condition1Control=condition1Control,
            condition2Control=condition2Control,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            highlightTerms=[term.strip() for term in highlightTerms.split(",") if term.strip()],
        )
        return HTMLResponse(content=volcano_control_html(payload))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render control volcano plot: {e}") from e


@router.get("/stats/{kind}/gsea/{direction}.png")
async def stats_gsea_route(
    kind: AnnotationKind,
    direction: str,
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    topN: int = 10,
    minTermSize: int = 20,
    maxTermSize: int = 300,
) -> Response:
    try:
        payload = EnrichmentRequest(
            kind=kind,
            condition1=condition1,
            condition2=condition2,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            topN=topN,
            minTermSize=minTermSize,
            maxTermSize=maxTermSize,
        )
        return _png_response(gsea_plot_png(payload, direction=direction))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render GSEA plot: {e}") from e


@router.get("/stats/{kind}/pathway-heatmap.png")
async def stats_pathway_heatmap_route(
    kind: AnnotationKind,
    pathway: str,
    conditions: str = "",
    valueType: str = "z",
    includeId: bool = True,
    header: bool = True,
    removeEmpty: bool = True,
    clusterRows: bool = False,
    clusterCols: bool = False,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 300,
) -> Response:
    try:
        condition_list = [value.strip() for value in conditions.split(",") if value.strip()]
        return _png_response(
            pathway_heatmap_png(
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render pathway heatmap: {e}") from e


@router.get("/stats/{kind}/simulation.html", response_class=HTMLResponse)
async def stats_simulation_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    varianceMultiplier: float = 1.0,
    sampleSizeOverride: int = 0,
) -> HTMLResponse:
    try:
        payload = SimulationRequest(
            kind=kind,
            condition1=condition1,
            condition2=condition2,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            varianceMultiplier=varianceMultiplier,
            sampleSizeOverride=sampleSizeOverride,
        )
        return HTMLResponse(content=simulation_html(payload))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render simulation plot: {e}") from e


@router.get("/peptide/rt.png")
async def peptide_rt_route(
    method: str = "Hexbin Plot",
    addLine: bool = False,
    bins: int = 1000,
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 15,
    dpi: int = 100,
) -> Response:
    try:
        return _png_response(
            peptide_rt_plot(
                method=method,
                add_line=addLine,
                bins=bins,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render peptide RT plot: {e}") from e


@router.get("/peptide/modification.png")
async def peptide_modification_route(
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 25,
    heightCm: float = 15,
    dpi: int = 100,
) -> Response:
    try:
        return _png_response(
            peptide_modification_plot(
                include_id=includeId,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render peptide modification plot: {e}") from e


@router.get("/peptide/missed-cleavage.png")
async def peptide_missed_cleavage_route(
    includeId: bool = False,
    text: bool = True,
    textSize: int = 8,
    header: bool = True,
    widthCm: float = 25,
    heightCm: float = 15,
    dpi: int = 100,
) -> Response:
    try:
        return _png_response(
            peptide_missed_cleavage_plot(
                include_id=includeId,
                text=text,
                text_size=textSize,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render peptide missed-cleavage plot: {e}") from e


@router.get("/imputation/{kind}/before-missing.png")
async def imputation_before_route(
    kind: AnnotationKind,
    qValue: float = 0.01,
    adjustStd: float = 1.0,
    seed: int = 1337,
    sampleWise: bool = False,
) -> Response:
    try:
        return _png_response(imputation_before_plot(kind, qValue, adjustStd, seed, sampleWise))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render imputation plot: {e}") from e


@router.get("/imputation/{kind}/overall-fit.png")
async def imputation_overall_route(
    kind: AnnotationKind,
    qValue: float = 0.01,
    adjustStd: float = 1.0,
    seed: int = 1337,
    sampleWise: bool = False,
) -> Response:
    try:
        return _png_response(imputation_overall_fit_plot(kind, qValue, adjustStd, seed, sampleWise))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render imputation plot: {e}") from e


@router.get("/imputation/{kind}/after-imputation.png")
async def imputation_after_route(
    kind: AnnotationKind,
    qValue: float = 0.01,
    adjustStd: float = 1.0,
    seed: int = 1337,
    sampleWise: bool = False,
) -> Response:
    try:
        return _png_response(imputation_after_plot(kind, qValue, adjustStd, seed, sampleWise))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render imputation plot: {e}") from e


@router.get("/distribution/{kind}/qqnorm.png")
async def distribution_qq_route(kind: AnnotationKind) -> Response:
    try:
        return _png_response(distribution_qqnorm_plot(kind))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QQ plot: {e}") from e


@router.get("/verification/{kind}/first-digit.png")
async def verification_first_digit_route(kind: AnnotationKind) -> Response:
    try:
        return _png_response(verification_first_digit_plot(kind))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render verification plot: {e}") from e


@router.get("/verification/{kind}/duplicate-pattern.png")
async def verification_duplicate_route(kind: AnnotationKind) -> Response:
    try:
        return _png_response(verification_duplicate_pattern_plot(kind))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render verification plot: {e}") from e


@router.get("/completeness/{kind}/missing-value.png")
async def completeness_missing_value_route(
    kind: AnnotationKind,
    binCount: int = 0,
    header: bool = True,
    text: bool = True,
    textSize: int = 8,
    color: str = "#2563eb",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            completeness_missing_value_plot(
                kind=kind,
                bin_count=binCount,
                header=header,
                text=text,
                text_size=textSize,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render completeness plot: {e}") from e


@router.get("/completeness/{kind}/missing-heatmap.png")
async def completeness_missing_heatmap_route(
    kind: AnnotationKind,
    includeId: bool = True,
    header: bool = True,
    widthCm: float = 10,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            completeness_missing_value_heatmap(
                kind=kind,
                include_id=includeId,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render completeness plot: {e}") from e


@router.get("/qc/{kind}/coverage.png")
async def qc_coverage_route(
    kind: AnnotationKind,
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    summary: bool = False,
    text: bool = False,
    textSize: int = 9,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_coverage_plot(
                kind=kind,
                include_id=includeId,
                header=header,
                legend=legend,
                summary=summary,
                text=text,
                text_size=textSize,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/coverage-table")
async def qc_coverage_table_route(
    kind: AnnotationKind,
    summary: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_coverage_table(kind=kind, summary=summary))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load coverage table: {e}") from e


@router.get("/qc/{kind}/options")
async def qc_options_route(kind: AnnotationKind) -> dict[str, list[str]]:
    annotation = get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        return {"conditions": []}
    conditions = [
        str(value)
        for value in annotation.metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
    ]
    return {"conditions": conditions}


@router.get("/qc/{kind}/intensity-histogram.png")
async def qc_hist_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_intensity_histogram_plot(
                kind=kind,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/boxplot.png")
async def qc_boxplot_route(
    kind: AnnotationKind,
    mode: str = "Mean",
    outliers: bool = False,
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    textSize: int = 9,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_boxplot_plot(
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/boxplot-table")
async def qc_boxplot_table_route(
    kind: AnnotationKind,
    mode: str = "Mean",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_boxplot_table(kind=kind, mode=mode))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load boxplot table: {e}") from e


@router.get("/qc/{kind}/cv.png")
async def qc_cv_route(
    kind: AnnotationKind,
    outliers: bool = False,
    header: bool = True,
    legend: bool = True,
    text: bool = False,
    textSize: int = 9,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_cv_plot(
                kind=kind,
                outliers=outliers,
                header=header,
                legend=legend,
                text=text,
                text_size=textSize,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/cv-table")
async def qc_cv_table_route(kind: AnnotationKind) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_cv_table(kind=kind))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load CV table: {e}") from e


@router.get("/qc/{kind}/pca.png")
async def qc_pca_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plotDim: str = "2D",
    addEllipses: bool = False,
    dotSize: int = 5,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_pca_plot(
                kind=kind,
                header=header,
                legend=legend,
                plot_dim=plotDim,
                add_ellipses=addEllipses,
                dot_size=dotSize,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/pca-interactive.html")
async def qc_pca_interactive_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    plotDim: str = "2D",
    addEllipses: bool = False,
    dotSize: int = 8,
    widthCm: float = 20,
    heightCm: float = 10,
) -> HTMLResponse:
    try:
        html = qc_pca_interactive_html(
            kind=kind,
            header=header,
            legend=legend,
            plot_dim=plotDim,
            add_ellipses=addEllipses,
            dot_size=dotSize,
            width_cm=widthCm,
            height_cm=heightCm,
        )
        return HTMLResponse(content=html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render interactive PCA plot: {e}") from e


@router.get("/qc/{kind}/abundance.png")
async def qc_abundance_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            qc_abundance_plot(
                kind=kind,
                header=header,
                legend=legend,
                condition=condition,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e


@router.get("/qc/{kind}/abundance-interactive.html")
async def qc_abundance_interactive_route(
    kind: AnnotationKind,
    header: bool = True,
    legend: bool = True,
    condition: str = "All Conditions",
    widthCm: float = 20,
    heightCm: float = 10,
) -> HTMLResponse:
    try:
        html = qc_abundance_interactive_html(
            kind=kind,
            header=header,
            legend=legend,
            condition=condition,
            width_cm=widthCm,
            height_cm=heightCm,
        )
        return HTMLResponse(content=html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render interactive abundance plot: {e}") from e


@router.get("/qc/{kind}/correlation.png")
async def qc_correlation_route(
    kind: AnnotationKind,
    method: str = "Matrix",
    includeId: bool = False,
    fullRange: bool = False,
    widthCm: float = 20,
    heightCm: float = 16,
    dpi: int = 400,
) -> Response:
    try:
        return _png_response(
            qc_correlation_plot(
                kind=kind,
                method=method,
                include_id=includeId,
                full_range=fullRange,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e) or "Correlation plot failed due to invalid or insufficient data.",
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e

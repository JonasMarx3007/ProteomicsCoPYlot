from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
    comparison_pearson_png,
    comparison_venn_png,
    completeness_missing_value_heatmap,
    completeness_missing_value_plot,
    completeness_missing_value_plot_peptide,
    completeness_missing_value_plot_precursor,
    distribution_qqnorm_plot,
    imputation_after_plot,
    imputation_before_plot,
    imputation_overall_fit_plot,
    phospho_coverage_png,
    phospho_distribution_png,
    phospho_sty_png,
    phosphosite_plot_png,
    qc_abundance_plot,
    qc_abundance_interactive_html,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_peptide_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_plot,
    qc_pca_interactive_html,
    single_protein_boxplot_plot,
    single_protein_heatmap_plot,
    single_protein_lineplot_plot,
    verification_duplicate_pattern_plot,
    verification_first_digit_plot,
)
from app.services.single_protein_tools import (
    single_protein_boxplot_table,
    single_protein_heatmap_table,
    single_protein_lineplot_table,
    single_protein_options,
)
from app.services.comparison_tools import (
    comparison_options,
    pearson_correlation_table,
    venn_table,
)
from app.services.phospho_tools import (
    ksea_uploaded_volcano_html,
    ksea_plot_png,
    ksea_table,
    phosprot_regulation_html,
    phosprot_regulation_png,
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


def _csv_values(raw: str) -> list[str]:
    return [value.strip() for value in str(raw).split(",") if value.strip()]


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
    kind: str,
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
        kind_normalized = kind.strip().lower()
        if kind_normalized == "peptide":
            return _png_response(
                completeness_missing_value_plot_peptide(
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
        if kind_normalized == "precursor":
            return _png_response(
                completeness_missing_value_plot_precursor(
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
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            return _png_response(
                completeness_missing_value_plot(
                    kind=kind_normalized,
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
        raise ValueError("Unsupported completeness dataset level.")
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
    kind: str,
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
        kind_normalized = kind.strip().lower()
        if kind_normalized == "peptide":
            return _png_response(
                qc_peptide_coverage_plot(
                    include_id=includeId,
                    header=header,
                    legend=legend,
                    width_cm=widthCm,
                    height_cm=heightCm,
                    dpi=dpi,
                )
            )
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            return _png_response(
                qc_coverage_plot(
                    kind=kind_normalized,
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
        raise ValueError("Unsupported QC dataset level.")
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


@router.get("/single-protein/{kind}/options")
async def single_protein_options_route(
    kind: AnnotationKind,
    tab: str = "boxplot",
) -> dict[str, list[str] | int]:
    try:
        return single_protein_options(kind=kind, tab=tab)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load single-protein options: {e}") from e


@router.get("/single-protein/{kind}/boxplot.png")
async def single_protein_boxplot_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    outliers: bool = False,
    dots: bool = False,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            single_protein_boxplot_plot(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                outliers=outliers,
                dots=dots,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render single-protein boxplot: {e}") from e


@router.get("/single-protein/{kind}/lineplot.png")
async def single_protein_lineplot_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            single_protein_lineplot_plot(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
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
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render single-protein lineplot: {e}") from e


@router.get("/single-protein/{kind}/heatmap.png")
async def single_protein_heatmap_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
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
) -> Response:
    try:
        return _png_response(
            single_protein_heatmap_plot(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render single-protein heatmap: {e}") from e


@router.get("/single-protein/{kind}/boxplot-table")
async def single_protein_boxplot_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            single_protein_boxplot_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load single-protein boxplot table: {e}") from e


@router.get("/single-protein/{kind}/lineplot-table")
async def single_protein_lineplot_table_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            single_protein_lineplot_table(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
                include_id=includeId,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load single-protein lineplot table: {e}") from e


@router.get("/single-protein/{kind}/heatmap-table")
async def single_protein_heatmap_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    includeId: bool = False,
    filterM1: bool = True,
    clusterRows: bool = False,
    clusterCols: bool = False,
    valueType: str = "log2",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            single_protein_heatmap_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                include_id=includeId,
                filter_m1=filterM1,
                cluster_rows=clusterRows,
                cluster_cols=clusterCols,
                value_type=valueType,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load single-protein heatmap table: {e}") from e


@router.get("/phospho/options")
async def phospho_options_route() -> dict[str, list[str]]:
    try:
        return phospho_options()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load phospho options: {e}") from e


@router.get("/phospho/phosphosite-plot.png")
async def phosphosite_plot_route(
    cutoff: float = 0.0,
    color: str = "#87CEEB",
    widthCm: float = 15,
    heightCm: float = 10,
    dpi: int = 100,
) -> Response:
    try:
        return _png_response(
            phosphosite_plot_png(
                cutoff=cutoff,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render phosphosite plot: {e}") from e


@router.get("/phospho/phosphosite-plot-table")
async def phosphosite_plot_table_route(
    cutoff: float = 0.0,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phosphosite_plot_table(cutoff=cutoff))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load phosphosite table: {e}") from e


@router.get("/phospho/coverage.png")
async def phospho_coverage_route(
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: str = "Normal",
    colorClassI: str = "#2563eb",
    colorNotClassI: str = "#f59e0b",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    conditions: str = "",
) -> Response:
    try:
        return _png_response(
            phospho_coverage_png(
                include_id=includeId,
                header=header,
                legend=legend,
                mode=mode,
                color_class_i=colorClassI,
                color_not_class_i=colorNotClassI,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                conditions=_csv_values(conditions),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render phospho coverage plot: {e}") from e


@router.get("/phospho/coverage-table")
async def phospho_coverage_table_route(
    includeId: bool = False,
    mode: str = "Normal",
    conditions: str = "",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            phospho_coverage_table(
                include_id=includeId,
                mode=mode,
                conditions=_csv_values(conditions),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load phospho coverage table: {e}") from e


@router.get("/phospho/distribution.png")
async def phospho_distribution_route(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    widthCm: float = 20,
    heightCm: float = 15,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            phospho_distribution_png(
                cutoff=cutoff,
                header=header,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render phospho distribution plot: {e}") from e


@router.get("/phospho/distribution-table")
async def phospho_distribution_table_route(
    cutoff: float = 0.0,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phospho_distribution_table(cutoff=cutoff))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load phospho distribution table: {e}") from e


@router.get("/phospho/ksea.png")
async def phospho_ksea_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 220,
) -> Response:
    try:
        return _png_response(
            ksea_plot_png(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render KSEA plot: {e}") from e


@router.get("/phospho/ksea-table")
async def phospho_ksea_table_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            ksea_table(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load KSEA table: {e}") from e


@router.post("/phospho/ksea-volcano.html", response_class=HTMLResponse)
async def phospho_ksea_uploaded_volcano_route(
    fileSt: UploadFile = File(...),
    fileTnc: UploadFile = File(...),
    pValueThreshold: float = Form(0.1),
    header: bool = Form(True),
    condition1: str = Form(""),
    condition2: str = Form(""),
    highlightGrk: bool = Form(False),
) -> HTMLResponse:
    if not fileSt.filename or not fileTnc.filename:
        raise HTTPException(status_code=400, detail="Both KSEA result files are required.")

    try:
        df_st = read_dataframe(fileSt.filename, fileSt.file)
        df_tnc = read_dataframe(fileTnc.filename, fileTnc.file)
        return HTMLResponse(
            content=ksea_uploaded_volcano_html(
                st_results=df_st,
                tnc_results=df_tnc,
                p_value_threshold=pValueThreshold,
                header=header,
                condition1=condition1,
                condition2=condition2,
                highlight_grk=highlightGrk,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate KSEA volcano: {e}") from e


@router.get("/phospho/phosprot-regulation.png")
async def phospho_phosprot_regulation_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 220,
) -> Response:
    try:
        return _png_response(
            phosprot_regulation_png(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                max_hover_sites=maxHoverSites,
                show_phosphosites=showPhosphosites,
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render phosprot regulation plot: {e}") from e


@router.get("/phospho/phosprot-regulation.html", response_class=HTMLResponse)
async def phospho_phosprot_regulation_html_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    header: bool = True,
) -> HTMLResponse:
    try:
        return HTMLResponse(
            content=phosprot_regulation_html(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                max_hover_sites=maxHoverSites,
                show_phosphosites=showPhosphosites,
                header=header,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render interactive phosprot regulation plot: {e}") from e


@router.get("/phospho/phosprot-regulation-table")
async def phospho_phosprot_regulation_table_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
) -> dict[str, list[dict[str, object]]]:
    try:
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load phosprot regulation table: {e}") from e


@router.get("/phospho/sty.png")
async def phospho_sty_route(
    header: bool = True,
    widthCm: float = 17.78,
    heightCm: float = 11.43,
    dpi: int = 140,
) -> Response:
    try:
        return _png_response(
            phospho_sty_png(
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render STY plot: {e}") from e


@router.get("/phospho/sty-table")
async def phospho_sty_table_route() -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phospho_sty_table())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load STY table: {e}") from e


@router.get("/comparison/{kind}/options")
async def comparison_options_route(
    kind: AnnotationKind,
) -> dict[str, list[str] | int]:
    try:
        return comparison_options(kind=kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load comparison options: {e}") from e


@router.get("/comparison/{kind}/pearson.png")
async def comparison_pearson_route(
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
) -> Response:
    try:
        return _png_response(
            comparison_pearson_png(
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render Pearson correlation: {e}") from e


@router.get("/comparison/{kind}/pearson-table")
async def comparison_pearson_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    sample1: str = "",
    sample2: str = "",
    condition1: str = "",
    condition2: str = "",
    alias1: str = "",
    alias2: str = "",
) -> dict[str, list[dict[str, object]]]:
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load Pearson table: {e}") from e


@router.get("/comparison/{kind}/venn.png")
async def comparison_venn_route(
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
) -> Response:
    try:
        return _png_response(
            comparison_venn_png(
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render Venn diagram: {e}") from e


@router.get("/comparison/{kind}/venn-table")
async def comparison_venn_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    first: str = "",
    second: str = "",
    third: str = "",
    alias1: str = "",
    alias2: str = "",
    alias3: str = "",
) -> dict[str, list[dict[str, object]]]:
    try:
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load Venn table: {e}") from e

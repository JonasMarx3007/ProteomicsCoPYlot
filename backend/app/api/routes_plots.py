from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.schemas.annotation import AnnotationKind
from app.schemas.dataset import CompletenessDatasetKind, DatasetKind
from app.schemas.data_tools import VisualizationDataSource
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
    AnovaRequest,
    EnrichmentRequest,
    HeatmapValueType,
    OraDirection,
    SimulationRequest,
    SimulationTestType,
    StatsTestType,
    VolcanoControlRequest,
    VolcanoRequest,
)
from app.services.annotation_store import get_annotation
from app.services.functions import (
    comparison_pearson_html,
    comparison_pearson_png,
    comparison_venn_png,
    completeness_missing_value_heatmap,
    completeness_missing_value_plot,
    completeness_missing_value_plot_peptide,
    completeness_missing_value_plot_precursor,
    distribution_qqnorm_plot,
    imputed_data_available,
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
    anova_png,
    ora_plot_png,
    pathway_heatmap_png,
    simulation_html,
    volcano_control_html,
    volcano_html,
)
from app.services.peptide_tools import (
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_interactive_html,
    peptide_rt_plot,
)
from app.services.plot_images import (
    _sample_label,
    parse_advanced_plot_settings,
    qc_pca_feature_summary,
)
from app.services.upload_limits import ensure_upload_size

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plots", tags=["plots"])


def _png_response(content: bytes) -> Response:
    return Response(
        content=content,
        media_type="image/png",
        headers={
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


@router.get("/stats/{kind}/volcano.html", response_class=HTMLResponse)
def stats_volcano_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    dataSource: str = "data",
    identifier: FeatureIdentifier = "workflow",
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: StatsTestType = "unpaired",
    useUncorrected: bool = False,
    highlightTerms: str = "",
    advanced: str = "",
) -> HTMLResponse:
    try:
        payload = VolcanoRequest(
            kind=kind,
            dataSource=dataSource,
            condition1=condition1,
            condition2=condition2,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            log2fcThreshold=log2fcThreshold,
            testType=testType,
            useUncorrected=useUncorrected,
            highlightTerms=[term.strip() for term in highlightTerms.split(",") if term.strip()],
        )
        return HTMLResponse(content=volcano_html(payload, advanced=parse_advanced_plot_settings(advanced)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render volcano plot")
        raise HTTPException(status_code=500, detail="Failed to render volcano plot.") from e


@router.get("/stats/{kind}/volcano-control.html", response_class=HTMLResponse)
def stats_volcano_control_route(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    condition1Control: str,
    condition2Control: str,
    dataSource: str = "data",
    identifier: FeatureIdentifier = "workflow",
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: StatsTestType = "unpaired",
    useUncorrected: bool = False,
    highlightTerms: str = "",
    advanced: str = "",
) -> HTMLResponse:
    try:
        payload = VolcanoControlRequest(
            kind=kind,
            dataSource=dataSource,
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
        return HTMLResponse(content=volcano_control_html(payload, advanced=parse_advanced_plot_settings(advanced)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render control volcano plot")
        raise HTTPException(status_code=500, detail="Failed to render control volcano plot.") from e


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
    nClusters: int = 4,
    selectedCluster: int | None = None,
    advanced: str = "",
) -> Response:
    try:
        payload = AnovaRequest(
            kind=kind,
            source=source,
            dataSource=dataSource,
            identifier=identifier,
            pValueThreshold=pValueThreshold,
            useUncorrected=useUncorrected,
            showDendrograms=showDendrograms,
            showLegend=showLegend,
            nClusters=nClusters,
        )
        return _png_response(anova_png(payload, selected_cluster=selectedCluster, advanced=parse_advanced_plot_settings(advanced)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render ANOVA plot")
        raise HTTPException(status_code=500, detail="Failed to render ANOVA plot.") from e


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
    advanced: str = "",
) -> Response:
    try:
        payload = EnrichmentRequest(
            kind=kind,
            source=source,
            dataSource=dataSource,
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
        return _png_response(ora_plot_png(payload, direction=direction, advanced=parse_advanced_plot_settings(advanced)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render ORA plot")
        raise HTTPException(status_code=500, detail="Failed to render ORA plot.") from e


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
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 300,
    advanced: str = "",
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
                data_source=dataSource,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render pathway heatmap")
        raise HTTPException(status_code=500, detail="Failed to render pathway heatmap.") from e


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
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render simulation plot")
        raise HTTPException(status_code=500, detail="Failed to render simulation plot.") from e


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
    try:
        return _png_response(
            peptide_rt_plot(
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render peptide RT plot")
        raise HTTPException(status_code=500, detail="Failed to render peptide RT plot.") from e


@router.get("/peptide/rt-interactive.html", response_class=HTMLResponse)
def peptide_rt_interactive_route(
    addLine: bool = False,
    header: bool = True,
    randomSeed: int = 69,
    widthCm: float = 20,
    heightCm: float = 15,
    advanced: str = "",
) -> HTMLResponse:
    try:
        return HTMLResponse(
            content=peptide_rt_interactive_html(
                add_line=addLine,
                header=header,
                sampling_seed=randomSeed,
                width_cm=widthCm,
                height_cm=heightCm,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render interactive peptide RT plot")
        raise HTTPException(status_code=500, detail="Failed to render interactive peptide RT plot.") from e


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
    try:
        return _png_response(
            peptide_modification_plot(
                include_id=includeId,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render peptide modification plot")
        raise HTTPException(status_code=500, detail="Failed to render peptide modification plot.") from e


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
    try:
        return _png_response(
            peptide_missed_cleavage_plot(
                include_id=includeId,
                text=text,
                text_size=textSize,
                header=header,
                protease=protease,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render peptide missed-cleavage plot")
        raise HTTPException(status_code=500, detail="Failed to render peptide missed-cleavage plot.") from e


def _csv_values(raw: str) -> list[str]:
    return [value.strip() for value in str(raw).split(",") if value.strip()]


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
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render imputation plot")
        raise HTTPException(status_code=500, detail="Failed to render imputation plot.") from e


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
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render imputation plot")
        raise HTTPException(status_code=500, detail="Failed to render imputation plot.") from e


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
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render imputation plot")
        raise HTTPException(status_code=500, detail="Failed to render imputation plot.") from e


@router.get("/distribution/{kind}/qqnorm.png")
def distribution_qq_route(
    kind: AnnotationKind,
    randomSeed: int = 187,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            distribution_qqnorm_plot(
                kind,
                random_seed=randomSeed,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QQ plot")
        raise HTTPException(status_code=500, detail="Failed to render QQ plot.") from e


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
) -> Response:
    try:
        kind_normalized = kind.strip().lower()
        advanced_settings = parse_advanced_plot_settings(advanced)
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
                    advanced=advanced_settings,
                    quantity_column=quantityColumn or None,
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
                    advanced=advanced_settings,
                    quantity_column=quantityColumn or None,
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
                    advanced=advanced_settings,
                )
            )
        raise ValueError("Unsupported completeness dataset level.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render completeness plot")
        raise HTTPException(status_code=500, detail="Failed to render completeness plot.") from e


@router.get("/completeness/{kind}/missing-heatmap.png")
def completeness_missing_heatmap_route(
    kind: AnnotationKind,
    includeId: bool = True,
    header: bool = True,
    widthCm: float = 10,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
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
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render completeness plot")
        raise HTTPException(status_code=500, detail="Failed to render completeness plot.") from e


@router.get("/qc/{kind}/coverage.png")
def qc_coverage_route(
    kind: DatasetKind,
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
) -> Response:
    try:
        kind_normalized = kind.strip().lower()
        advanced_settings = parse_advanced_plot_settings(advanced)
        if kind_normalized == "peptide":
            return _png_response(
                qc_peptide_coverage_plot(
                    include_id=includeId,
                    header=header,
                    legend=legend,
                    width_cm=widthCm,
                    height_cm=heightCm,
                    dpi=dpi,
                    advanced=advanced_settings,
                    quantity_column=quantityColumn or None,
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
                    random_seed=randomSeed,
                    width_cm=widthCm,
                    height_cm=heightCm,
                    dpi=dpi,
                    advanced=advanced_settings,
                )
            )
        raise ValueError("Unsupported QC dataset level.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


@router.get("/qc/{kind}/coverage-table")
def qc_coverage_table_route(
    kind: AnnotationKind,
    summary: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_coverage_table(kind=kind, summary=summary))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load coverage table")
        raise HTTPException(status_code=500, detail="Failed to load coverage table.") from e


@router.get("/qc/{kind}/pca-features")
def qc_pca_features_route(
    kind: AnnotationKind,
    dataSource: str = "data",
    plotDim: PlotDimension = "2D",
) -> dict[str, object]:
    try:
        return qc_pca_feature_summary(kind, data_source=dataSource, plot_dim=plotDim)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to summarise PCA features")
        raise HTTPException(status_code=500, detail="Failed to summarise PCA features.") from e


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
    try:
        return _png_response(
            qc_intensity_histogram_plot(
                kind=kind,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


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
    boxBorderColor: str = "",
    boxMedianColor: str = "",
    boxOutlierColor: str = "",
    boxOutlierEdgeColor: str = "",
    boxOutlierSize: float | None = None,
) -> Response:
    try:
        advanced_settings = parse_advanced_plot_settings(advanced)
        if boxBorderColor.strip():
            advanced_settings["boxBorderColor"] = boxBorderColor.strip()
        if boxMedianColor.strip():
            advanced_settings["boxMedianColor"] = boxMedianColor.strip()
        if boxOutlierColor.strip():
            advanced_settings["boxOutlierColor"] = boxOutlierColor.strip()
        if boxOutlierEdgeColor.strip():
            advanced_settings["boxOutlierEdgeColor"] = boxOutlierEdgeColor.strip()
        if boxOutlierSize is not None and boxOutlierSize > 0:
            advanced_settings["boxOutlierSize"] = boxOutlierSize
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
                advanced=advanced_settings,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


@router.get("/qc/{kind}/boxplot-table")
def qc_boxplot_table_route(
    kind: AnnotationKind,
    mode: BoxplotMode = "Mean",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_boxplot_table(kind=kind, mode=mode))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load boxplot table")
        raise HTTPException(status_code=500, detail="Failed to load boxplot table.") from e


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
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


@router.get("/qc/{kind}/cv-table")
def qc_cv_table_route(kind: AnnotationKind) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(qc_cv_table(kind=kind))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load CV table")
        raise HTTPException(status_code=500, detail="Failed to load CV table.") from e


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
    dbscanEps: float = 0.5,
    dbscanMinSamples: int = 2,
    randomState: int = 42,
    scaling: FeatureScaling = "auto",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    try:
        advanced_settings = parse_advanced_plot_settings(advanced)
        return _png_response(
            qc_pca_plot(
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
                dbscan_eps=dbscanEps,
                dbscan_min_samples=dbscanMinSamples,
                random_state=randomState,
                scaling=scaling,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=advanced_settings,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


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
    dbscanEps: float = 0.5,
    dbscanMinSamples: int = 2,
    randomState: int = 42,
    scaling: FeatureScaling = "auto",
    widthCm: float = 20,
    heightCm: float = 10,
    advanced: str = "",
) -> HTMLResponse:
    try:
        html = qc_pca_interactive_html(
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
            dbscan_eps=dbscanEps,
            dbscan_min_samples=dbscanMinSamples,
            random_state=randomState,
            scaling=scaling,
            width_cm=widthCm,
            height_cm=heightCm,
            advanced=parse_advanced_plot_settings(advanced),
        )
        return HTMLResponse(content=html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render interactive PCA plot")
        raise HTTPException(status_code=500, detail="Failed to render interactive PCA plot.") from e


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
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


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
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render interactive abundance plot")
        raise HTTPException(status_code=500, detail="Failed to render interactive abundance plot.") from e


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
    correlationColorMap: str = "",
) -> Response:
    try:
        advanced_settings = parse_advanced_plot_settings(advanced)
        if correlationColorMap.strip():
            advanced_settings["correlationColorMap"] = correlationColorMap.strip()
        return _png_response(
            qc_correlation_plot(
                kind=kind,
                method=method,
                include_id=includeId,
                full_range=fullRange,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=advanced_settings,
            )
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e) or "Correlation plot failed due to invalid or insufficient data.",
        ) from e
    except Exception as e:
        LOGGER.exception("Failed to render QC plot")
        raise HTTPException(status_code=500, detail="Failed to render QC plot.") from e


@router.get("/single-protein/{kind}/options")
def single_protein_options_route(
    kind: AnnotationKind,
    tab: SingleProteinTab = "boxplot",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
) -> dict[str, object]:
    try:
        return single_protein_options(
            kind=kind,
            tab=tab,
            identifier=identifier,
            data_source=dataSource,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load single-protein options")
        raise HTTPException(status_code=500, detail="Failed to load single-protein options.") from e


@router.get("/single-protein/{kind}/boxplot.png")
def single_protein_boxplot_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
    outliers: bool = False,
    dots: bool = False,
    randomSeed: int = 69,
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            single_protein_boxplot_plot(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
                outliers=outliers,
                dots=dots,
                random_seed=randomSeed,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render single-protein boxplot")
        raise HTTPException(status_code=500, detail="Failed to render single-protein boxplot.") from e


@router.get("/single-protein/{kind}/lineplot.png")
def single_protein_lineplot_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
    header: bool = True,
    legend: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            single_protein_lineplot_plot(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
                include_id=includeId,
                identifier=identifier,
                data_source=dataSource,
                header=header,
                legend=legend,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render single-protein lineplot")
        raise HTTPException(status_code=500, detail="Failed to render single-protein lineplot.") from e


@router.get("/single-protein/{kind}/heatmap.png")
def single_protein_heatmap_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
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
    try:
        return _png_response(
            single_protein_heatmap_plot(
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render single-protein heatmap")
        raise HTTPException(status_code=500, detail="Failed to render single-protein heatmap.") from e


@router.get("/single-protein/{kind}/boxplot-table")
def single_protein_boxplot_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            single_protein_boxplot_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load single-protein boxplot table")
        raise HTTPException(status_code=500, detail="Failed to load single-protein boxplot table.") from e


@router.get("/single-protein/{kind}/lineplot-table")
def single_protein_lineplot_table_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    includeId: bool = False,
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
) -> dict[str, list[dict[str, object]]]:
    try:
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load single-protein lineplot table")
        raise HTTPException(status_code=500, detail="Failed to load single-protein lineplot table.") from e


@router.get("/single-protein/{kind}/heatmap-table")
def single_protein_heatmap_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "data",
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
                identifier=identifier,
                data_source=dataSource,
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
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load single-protein heatmap table")
        raise HTTPException(status_code=500, detail="Failed to load single-protein heatmap table.") from e


@router.get("/phospho/options")
def phospho_options_route() -> dict[str, object]:
    try:
        return phospho_options()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load phospho options")
        raise HTTPException(status_code=500, detail="Failed to load phospho options.") from e


@router.get("/phospho/phosphosite-plot.png")
def phosphosite_plot_route(
    cutoff: float = 0.0,
    color: str = "#87CEEB",
    widthCm: float = 15,
    heightCm: float = 10,
    dpi: int = 100,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            phosphosite_plot_png(
                cutoff=cutoff,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render phosphosite plot")
        raise HTTPException(status_code=500, detail="Failed to render phosphosite plot.") from e


@router.get("/phospho/phosphosite-plot-table")
def phosphosite_plot_table_route(
    cutoff: float = 0.0,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phosphosite_plot_table(cutoff=cutoff))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load phosphosite table")
        raise HTTPException(status_code=500, detail="Failed to load phosphosite table.") from e


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
    try:
        return _png_response(
            phospho_coverage_png(
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render phospho coverage plot")
        raise HTTPException(status_code=500, detail="Failed to render phospho coverage plot.") from e


@router.get("/phospho/coverage-table")
def phospho_coverage_table_route(
    includeId: bool = False,
    mode: PhosphoCoverageMode = "Normal",
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
        LOGGER.exception("Failed to load phospho coverage table")
        raise HTTPException(status_code=500, detail="Failed to load phospho coverage table.") from e


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
    try:
        return _png_response(
            phospho_distribution_png(
                cutoff=cutoff,
                header=header,
                color=color,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render phospho distribution plot")
        raise HTTPException(status_code=500, detail="Failed to render phospho distribution plot.") from e


@router.get("/phospho/distribution-table")
def phospho_distribution_table_route(
    cutoff: float = 0.0,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phospho_distribution_table(cutoff=cutoff))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load phospho distribution table")
        raise HTTPException(status_code=500, detail="Failed to load phospho distribution table.") from e


@router.get("/phospho/ksea.png")
def phospho_ksea_route(
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
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 12,
    dpi: int = 220,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            ksea_plot_png(
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
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render KSEA plot")
        raise HTTPException(status_code=500, detail="Failed to render KSEA plot.") from e


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
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            ksea_table(
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load KSEA table")
        raise HTTPException(status_code=500, detail="Failed to load KSEA table.") from e


@router.post("/phospho/ksea-volcano.html", response_class=HTMLResponse)
def phospho_ksea_uploaded_volcano_route(
    fileSt: UploadFile = File(...),
    fileTnc: UploadFile = File(...),
    pValueThreshold: float = Form(0.1),
    header: bool = Form(True),
    condition1: str = Form(""),
    condition2: str = Form(""),
    annotateHits: bool = Form(False),
    advanced: str = Form(""),
) -> HTMLResponse:
    if not fileSt.filename or not fileTnc.filename:
        raise HTTPException(status_code=400, detail="Both KSEA result files are required.")

    try:
        ensure_upload_size(fileSt, label="KSEA S/T result file")
        ensure_upload_size(fileTnc, label="KSEA Y result file")
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
                annotate_hits=annotateHits,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to generate KSEA volcano")
        raise HTTPException(status_code=500, detail="Failed to generate KSEA volcano.") from e


@router.get("/phospho/phosprot-regulation.png")
def phospho_phosprot_regulation_route(
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
    advanced: str = "",
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
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render phosprot regulation plot")
        raise HTTPException(status_code=500, detail="Failed to render phosprot regulation plot.") from e


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
    header: bool = True,
    advanced: str = "",
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
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render interactive phosprot regulation plot")
        raise HTTPException(status_code=500, detail="Failed to render interactive phosprot regulation plot.") from e


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
        LOGGER.exception("Failed to load phosprot regulation table")
        raise HTTPException(status_code=500, detail="Failed to load phosprot regulation table.") from e


@router.get("/phospho/sty.png")
def phospho_sty_route(
    header: bool = True,
    widthCm: float = 17.78,
    heightCm: float = 11.43,
    dpi: int = 140,
    advanced: str = "",
) -> Response:
    try:
        return _png_response(
            phospho_sty_png(
                header=header,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render STY plot")
        raise HTTPException(status_code=500, detail="Failed to render STY plot.") from e


@router.get("/phospho/sty-table")
def phospho_sty_table_route() -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(phospho_sty_table())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load STY table")
        raise HTTPException(status_code=500, detail="Failed to load STY table.") from e


@router.get("/comparison/{kind}/options")
def comparison_options_route(
    kind: AnnotationKind,
    dataSource: VisualizationDataSource = "data",
) -> dict[str, list[str] | int | bool | str]:
    try:
        return comparison_options(kind=kind, data_source=dataSource)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load comparison options")
        raise HTTPException(status_code=500, detail="Failed to load comparison options.") from e


@router.get("/comparison/{kind}/pearson.png")
def comparison_pearson_route(
    kind: AnnotationKind,
    mode: str = "Single",
    dataSource: VisualizationDataSource = "data",
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
    try:
        return _png_response(
            comparison_pearson_png(
                kind=kind,
                mode=mode,
                data_source=dataSource,
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render Pearson correlation")
        raise HTTPException(status_code=500, detail="Failed to render Pearson correlation.") from e


@router.get("/comparison/{kind}/pearson.html", response_class=HTMLResponse)
def comparison_pearson_interactive_route(
    kind: AnnotationKind,
    mode: str = "Single",
    dataSource: VisualizationDataSource = "data",
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
    try:
        return HTMLResponse(
            content=comparison_pearson_html(
                kind=kind,
                mode=mode,
                data_source=dataSource,
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
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render interactive Pearson correlation")
        raise HTTPException(status_code=500, detail="Failed to render interactive Pearson correlation.") from e


@router.get("/comparison/{kind}/pearson-table")
def comparison_pearson_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    dataSource: VisualizationDataSource = "data",
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
                data_source=dataSource,
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
        LOGGER.exception("Failed to load Pearson table")
        raise HTTPException(status_code=500, detail="Failed to load Pearson table.") from e


@router.get("/comparison/{kind}/venn.png")
def comparison_venn_route(
    kind: AnnotationKind,
    mode: str = "Single",
    dataSource: VisualizationDataSource = "data",
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
) -> Response:
    try:
        return _png_response(
            comparison_venn_png(
                kind=kind,
                mode=mode,
                data_source=dataSource,
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
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ModuleNotFoundError as e:
        # Our own message names the missing package and how to install it,
        # which is actionable and discloses nothing about the host.
        LOGGER.exception("Optional dependency missing")
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render Venn diagram")
        raise HTTPException(status_code=500, detail="Failed to render Venn diagram.") from e


@router.get("/comparison/{kind}/venn-table")
def comparison_venn_table_route(
    kind: AnnotationKind,
    mode: str = "Single",
    dataSource: VisualizationDataSource = "data",
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
                data_source=dataSource,
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
        LOGGER.exception("Failed to load Venn table")
        raise HTTPException(status_code=500, detail="Failed to load Venn table.") from e

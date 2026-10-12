from __future__ import annotations

"""Imputation previews, the Q-Q plot and completeness plots (`/api/plots/{imputation,distribution,completeness}/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from typing import cast

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.schemas.annotation import AnnotationKind
from app.schemas.dataset import CompletenessDatasetKind
from app.services.completeness_tools import (
    completeness_missing_value_heatmap,
    completeness_missing_value_plot,
)
from app.services.plot_images import (
    distribution_qqnorm_plot,
    imputation_after_plot,
    imputation_before_plot,
    imputation_overall_fit_plot,
)
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.api.plot_responses import plot_errors, png_response

router = APIRouter()  # mounted under /api/plots by routes_plots


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
        return png_response(
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
        return png_response(
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
        return png_response(
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
        return png_response(
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
            response = png_response(content)
            if token:
                response.headers["X-CoPYlot-Notebook"] = token
            return response
        if kind_normalized in {"protein", "phospho", "phosprot"}:
            return _completeness_notebook_plot(
                "missing-value",
                table_include_id=tableIncludeId,
                outlier_threshold=outlierThreshold,
                kind=cast(AnnotationKind, kind_normalized),
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


def _completeness_notebook_plot(plot: str, *, kind: AnnotationKind, table_include_id: bool, outlier_threshold: float, **options) -> Response:
    from app.services.notebook_completeness import render_completeness
    from app.services.notebook_provenance import NotebookProvenanceError

    try:
        content, token = render_completeness(kind, plot=plot, table_include_id=table_include_id,
                                             outlier_threshold=outlier_threshold, **options)
    except NotebookProvenanceError as exc:
        from urllib.parse import quote
        renderer = completeness_missing_value_plot if plot == "missing-value" else completeness_missing_value_heatmap
        response = png_response(renderer(kind=kind, **options))
        response.headers["X-CoPYlot-Notice"] = quote(f"Notebook export unavailable: {exc} The plot is unchanged.")
        return response
    response = png_response(content)
    if token:
        response.headers["X-CoPYlot-Notebook"] = token
    return response

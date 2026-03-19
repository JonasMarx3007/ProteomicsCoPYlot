from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.schemas.annotation import AnnotationKind
from app.services.annotation_store import get_annotation
from app.services.plot_images import (
    distribution_qqnorm_plot,
    imputation_after_plot,
    imputation_before_plot,
    imputation_overall_fit_plot,
    qc_abundance_plot,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_plot,
    verification_duplicate_pattern_plot,
    verification_first_digit_plot,
)

router = APIRouter(prefix="/api/plots", tags=["plots"])


def _png_response(content: bytes) -> Response:
    return Response(content=content, media_type="image/png")


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


@router.get("/qc/{kind}/correlation.png")
async def qc_correlation_route(
    kind: AnnotationKind,
    method: str = "Matrix",
    includeId: bool = False,
    fullRange: bool = False,
    widthCm: float = 10,
    heightCm: float = 8,
    dpi: int = 100,
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
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render QC plot: {e}") from e

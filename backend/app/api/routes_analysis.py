from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas.analysis import AnalysisVolcanoRequest, AnalysisVolcanoResponse
from app.schemas.annotation import AnnotationKind
from app.services.analysis_functions import (
    analysis_boxplot_png,
    analysis_boxplot_table,
    analysis_lineplot_png,
    analysis_lineplot_table,
    analysis_volcano_data,
)

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _csv_values(raw: str) -> list[str]:
    return [value.strip() for value in str(raw).split(",") if value.strip()]


def _png_response(content: bytes) -> Response:
    return Response(content=content, media_type="image/png")


def _table_rows(df) -> dict[str, list[dict[str, object]]]:
    safe_df = df.fillna("")
    return {"rows": safe_df.to_dict(orient="records")}


@router.post("/volcano/data", response_model=AnalysisVolcanoResponse)
async def analysis_volcano_data_route(payload: AnalysisVolcanoRequest) -> AnalysisVolcanoResponse:
    try:
        return analysis_volcano_data(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load analysis volcano data: {e}") from e


@router.get("/boxplot.png")
async def analysis_boxplot_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: str = "workflow",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            analysis_boxplot_png(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                identifier=identifier,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render analysis boxplot: {e}") from e


@router.get("/boxplot-table")
async def analysis_boxplot_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: str = "workflow",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            analysis_boxplot_table(
                kind=kind,
                protein=protein,
                conditions=_csv_values(conditions),
                identifier=identifier,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load analysis boxplot table: {e}") from e


@router.get("/lineplot.png")
async def analysis_lineplot_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    identifier: str = "workflow",
    includeId: bool = False,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
) -> Response:
    try:
        return _png_response(
            analysis_lineplot_png(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
                identifier=identifier,
                include_id=includeId,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render analysis lineplot: {e}") from e


@router.get("/lineplot-table")
async def analysis_lineplot_table_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    identifier: str = "workflow",
    includeId: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            analysis_lineplot_table(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
                identifier=identifier,
                include_id=includeId,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load analysis lineplot table: {e}") from e

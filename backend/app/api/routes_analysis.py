from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas.analysis import AnalysisVolcanoRequest, AnalysisVolcanoResponse
from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import VisualizationDataSource
from app.schemas.qc import FeatureIdentifier
from app.services.functions import parse_selection_list
from app.services.analysis_functions import (
    analysis_boxplot_png,
    analysis_boxplot_table,
    analysis_lineplot_png,
    analysis_lineplot_table,
    analysis_volcano_data,
)

LOGGER = logging.getLogger(__name__)


router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _csv_values(raw: str) -> list[str]:
    return parse_selection_list(raw)


def _png_response(content: bytes) -> Response:
    return Response(content=content, media_type="image/png")


def _table_rows(df) -> dict[str, list[dict[str, object]]]:
    safe_df = df.fillna("")
    return {"rows": safe_df.to_dict(orient="records")}


@router.post("/volcano/data", response_model=AnalysisVolcanoResponse)
def analysis_volcano_data_route(payload: AnalysisVolcanoRequest) -> AnalysisVolcanoResponse:
    try:
        return analysis_volcano_data(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load analysis volcano data")
        raise HTTPException(status_code=500, detail="Failed to load analysis volcano data.") from e


@router.get("/boxplot.png")
def analysis_boxplot_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "log2",
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
                data_source=dataSource,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render analysis boxplot")
        raise HTTPException(status_code=500, detail="Failed to render analysis boxplot.") from e


@router.get("/boxplot-table")
def analysis_boxplot_table_route(
    kind: AnnotationKind,
    protein: str,
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "log2",
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            analysis_boxplot_table(
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
        LOGGER.exception("Failed to load analysis boxplot table")
        raise HTTPException(status_code=500, detail="Failed to load analysis boxplot table.") from e


@router.get("/lineplot.png")
def analysis_lineplot_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "log2",
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
                data_source=dataSource,
                include_id=includeId,
                width_cm=widthCm,
                height_cm=heightCm,
                dpi=dpi,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to render analysis lineplot")
        raise HTTPException(status_code=500, detail="Failed to render analysis lineplot.") from e


@router.get("/lineplot-table")
def analysis_lineplot_table_route(
    kind: AnnotationKind,
    proteins: str = "",
    conditions: str = "",
    identifier: FeatureIdentifier = "workflow",
    dataSource: VisualizationDataSource = "log2",
    includeId: bool = False,
) -> dict[str, list[dict[str, object]]]:
    try:
        return _table_rows(
            analysis_lineplot_table(
                kind=kind,
                proteins=_csv_values(proteins),
                conditions=_csv_values(conditions),
                identifier=identifier,
                data_source=dataSource,
                include_id=includeId,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        LOGGER.exception("Failed to load analysis lineplot table")
        raise HTTPException(status_code=500, detail="Failed to load analysis lineplot table.") from e

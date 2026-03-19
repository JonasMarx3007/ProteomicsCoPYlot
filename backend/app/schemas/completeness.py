from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.annotation import AnnotationKind


class CompletenessTablesResponse(BaseModel):
    kind: AnnotationKind
    overallMissingPercent: float
    outlierThreshold: float
    outliers: list[str]
    sampleSummary: list[dict[str, Any]]
    featureSummary: list[dict[str, Any]]


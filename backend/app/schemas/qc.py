from __future__ import annotations

from pydantic import BaseModel, Field

from typing import Literal

from app.schemas.annotation import AnnotationKind
from app.schemas.data_tools import DataSource, HistogramBin

# How features are weighted before a projection. "auto" keeps each method's
# established default: PCA centred, UMAP and t-SNE on unit variance.
FeatureScaling = Literal["auto", "centered", "unit_variance"]

# Enumerated plot controls. Typed so FastAPI rejects an unexpected value instead
# of letting it reach a service that silently substitutes its default -- the UI
# then renders something other than what was asked for, with no error.
PlotDimension = Literal["2D", "3D"]
PcaColorBy = Literal["Condition", "Cluster"]
BoxplotMode = Literal["Mean", "Single"]
PhosphoCoverageMode = Literal["Normal", "Summary"]
SingleProteinTab = Literal["boxplot", "lineplot", "heatmap"]
FeatureIdentifier = Literal["workflow", "genes"]



class SampleMetricPoint(BaseModel):
    sample: str
    value: float


class BoxplotPoint(BaseModel):
    sample: str
    min: float
    q1: float
    median: float
    q3: float
    max: float


class ConditionCvPoint(BaseModel):
    """Replicate CV for one condition, summarised across features.

    CV is computed per feature across the replicates of a condition, on the
    original (linear) intensity scale -- the only form in which a coefficient of
    variation is meaningful. It is deliberately not a per-sample number: a CV
    needs replicates to vary across, so a single sample does not have one.
    """

    condition: str
    mean: float
    median: float
    q1: float
    q3: float
    lowerWhisker: float
    upperWhisker: float


class QcSummaryResponse(BaseModel):
    kind: AnnotationKind
    sourceUsed: DataSource
    sampleColumns: list[str]
    coverage: list[SampleMetricPoint]
    intensityHistogram: list[HistogramBin]
    boxplot: list[BoxplotPoint]
    cv: list[ConditionCvPoint]
    warnings: list[str] = Field(default_factory=list)


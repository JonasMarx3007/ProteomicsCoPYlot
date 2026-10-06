from __future__ import annotations

from typing import Literal

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

"""The advanced plot settings: every key the panel writes and a renderer reads.

The settings travel as one JSON object in each plot route's `advanced` query
parameter, so FastAPI never sees their shape. This model is that shape, written
down once. It is not used to parse the parameter -- a renderer still reads the
plain dict, and an unknown key is still ignored -- it is the vocabulary three
checks hold the code to:

* `frontend/src/lib/apiContract.ts`: the frontend's `AdvancedPlotSettings` type
  has exactly these keys (compile time, through the generated OpenAPI types);
* `frontend/tests/component/advanced-panel-keys.test.tsx`: the panel, with every
  card shown and every control changed, writes exactly the keys not marked
  `x-panel: false` (none today: keys an older panel wrote are migrated by
  `migrate_advanced_plot_settings` instead), offers exactly the values of each
  enumerated one, and the URL compaction keeps every one of them;
* `tests/contracts/test_advanced_settings_reach_the_renderers.py`: the plot
  routes, rendering real data, read every key here and no key that is not.

The enumerations come from the renderers' own tables, so a shape or font added
to the backend and not to the panel fails the second check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.services.plot_styling import (
    _LINE_STYLE_NAMES,
    _PLOT_THEME_MAP,
    MARKER_SHAPES,
    PLOT_FONTS,
)

MarkerShape = Literal[tuple(MARKER_SHAPES)]  # type: ignore[valid-type]
FontName = Literal[tuple(PLOT_FONTS)]  # type: ignore[valid-type]
LineStyle = Literal[tuple(sorted(_LINE_STYLE_NAMES))]  # type: ignore[valid-type]
PlotTheme = Literal[("default", *_PLOT_THEME_MAP)]  # type: ignore[valid-type]
# The renderers' own spelling: "x" draws vertical lines, "y" horizontal ones.
GridLineAxis = Literal["both", "x", "y"]


class AdvancedTextElementSettings(BaseModel):
    """A title or axis label, styled on its own."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    size: float | None = None
    xOffset: float | None = None
    yOffset: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None


class AdvancedPlotSettings(BaseModel):
    """One plot's appearance overrides. Absent means the plot's own choice."""

    model_config = ConfigDict(extra="forbid")

    titleElement: AdvancedTextElementSettings | None = None
    xLabelElement: AdvancedTextElementSettings | None = None
    yLabelElement: AdvancedTextElementSettings | None = None
    xTickLabelSize: float | None = None
    yTickLabelSize: float | None = None
    xTickLabelRotation: float | None = None
    yTickLabelRotation: float | None = None
    legendFontSize: float | None = None
    legendXOffset: float | None = None
    legendYOffset: float | None = None
    # The legend as an element rather than just a font size. `legendVisible` and
    # `legendFrame` are tri-state on the backend: absent leaves whatever the plot
    # itself chose.
    # Moved out of every page's options row, where "Toggle Header" appeared at 20
    # call sites under three different labels for one setting.
    titleVisible: bool | None = None
    legendVisible: bool | None = None
    legendTitle: str | None = None
    legendTextColor: str | None = None
    legendFrame: bool | None = None
    xTickLabelColor: str | None = None
    yTickLabelColor: str | None = None
    referenceLineColor: str | None = None
    referenceLineVisible: bool | None = None
    referenceLineLegend: bool | None = None
    referenceLineStyle: LineStyle | None = None
    referenceLineWidth: float | None = None
    rowLabelSize: float | None = None
    rowLabelColor: str | None = None
    # The face every text in the figure is drawn in, and the five elements that
    # may disagree with it. An element left empty follows `fontFamily`; every
    # name here has to be a key of PLOT_FONTS in backend/app/services/plot_images.py.
    fontFamily: FontName | None = None
    titleFontFamily: FontName | None = None
    axisLabelFontFamily: FontName | None = None
    tickFontFamily: FontName | None = None
    legendFontFamily: FontName | None = None
    valueLabelFontFamily: FontName | None = None
    boxBorderColor: str | None = None
    boxMedianColor: str | None = None
    boxOutlierColor: str | None = None
    boxOutlierEdgeColor: str | None = None
    boxOutlierSize: float | None = None
    # Data points drawn over a box, which are a different class of dot from the
    # outlier fliers beside them and so get their own controls.
    boxPointSize: float | None = None
    boxPointAlpha: float | None = None
    boxPointEdgeColor: str | None = None
    boxPointEdgeWidth: float | None = None
    # The single-class plots: PCA, correlation, Q-Q, abundance, coverage
    # overlays, RT. Sizes are diameters in points, so one number means the same
    # dot whichever renderer draws it.
    markerSize: float | None = None
    markerAlpha: float | None = None
    markerEdgeColor: str | None = None
    markerEdgeWidth: float | None = None
    markerShape: MarkerShape | None = None
    # Per-condition overrides. What is drawn is `this condition's value ?? the
    # general one ?? the plot's own default`, and choosing a general value clears
    # the map beside it, so every group snaps to it and can be pulled off again
    # one at a time.
    conditionMarkerSizes: dict[str, float] | None = None
    conditionMarkerShapes: dict[str, MarkerShape] | None = None
    conditionMarkerAlphas: dict[str, float] | None = None
    conditionMarkerEdgeWidths: dict[str, float] | None = None
    conditionMarkerEdgeColors: dict[str, str] | None = None
    # The volcano has three classes of point in one figure and they are read
    # differently, so each is sized and faded on its own.
    volcanoUpSize: float | None = None
    volcanoUpAlpha: float | None = None
    volcanoUpColor: str | None = None
    volcanoDownSize: float | None = None
    volcanoDownAlpha: float | None = None
    volcanoDownColor: str | None = None
    volcanoNsSize: float | None = None
    volcanoNsAlpha: float | None = None
    volcanoNsColor: str | None = None
    volcanoHighlightSize: float | None = None
    volcanoHighlightColor: str | None = None
    volcanoLabelSize: float | None = None
    # Colours that used to be pickers in a plot's own options row.
    barColor: str | None = None
    classIColor: str | None = None
    classNotIColor: str | None = None
    vennColor1: str | None = None
    vennColor2: str | None = None
    vennColor3: str | None = None
    markerColor: str | None = None
    # The value labels drawn on bars and boxes. Was a per-page "Text Size",
    # clamped 6-20, 6-24 and 6-unbounded on the three pages that had it.
    valueLabelSize: float | None = None
    correlationColorMap: str | None = None
    backgroundColor: str | None = None
    transparentBackground: bool | None = None
    plotTheme: PlotTheme | None = None
    axisLineColor: str | None = None
    axisLineWidth: float | None = None
    axisLineStyle: LineStyle | None = None
    axisLineTop: bool | None = None
    axisLineRight: bool | None = None
    axisLineBottom: bool | None = None
    axisLineLeft: bool | None = None
    gridLineVisible: bool | None = None
    gridLineAxis: GridLineAxis | None = None
    gridLineColor: str | None = None
    gridLineWidth: float | None = None
    gridLineStyle: LineStyle | None = None
    conditionLabels: dict[str, str] | None = None
    sampleLabels: dict[str, str] | None = None
    conditionColors: dict[str, str] | None = None


ADVANCED_PLOT_SETTING_KEYS: frozenset[str] = frozenset(AdvancedPlotSettings.model_fields)
PANEL_SETTING_KEYS: frozenset[str] = frozenset(
    name
    for name, field in AdvancedPlotSettings.model_fields.items()
    if (field.json_schema_extra or {}).get("x-panel") is not False
)

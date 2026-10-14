import { AssistantInput, AssistantSelect } from "../AssistantFields";
import { isHexColor } from "../../lib/textAndColor";
import { useEffect, useState, type ReactNode } from "react";
import type { AdvancedPlotSettings, AdvancedTextElementSettings } from "../../lib/types";

type ElementKey = "titleElement" | "xLabelElement" | "yLabelElement";

export type AdvancedPlotVisibleControls = {
  textElements?: boolean;
  tickControls?: boolean;
  legendControls?: boolean;
  // Any plot that draws a threshold, a fit or a guide over its data.
  referenceLineColor?: boolean;
  // The "Show" box in the Reference line card. False where the plot switches
  // its line in its own options (the coverage plot): the card then only styles
  // a line that is there.
  referenceLineToggle?: boolean;
  // The "Legend entry" box: only for a plot that names its line in the legend
  // (the coverage total) and only while that legend is drawn.
  referenceLineLegend?: boolean;
  fontControls?: boolean;
  conditionLabels?: boolean;
  sampleLabels?: boolean;
  conditionColors?: boolean;
  boxplotStyle?: boolean;
  boxplotOutliers?: boolean;
  // Dots drawn over a box, as distinct from the outlier fliers beside them.
  boxplotPoints?: boolean;
  correlationGradient?: boolean;
  backgroundControls?: boolean;
  axisLineControls?: boolean;
  // One class of dot: PCA, correlation, Q-Q, abundance, RT.
  markerStyle?: boolean;
  // The plot draws its points in per-condition groups, so each condition can
  // override the general point settings. Only meaningful with `markerStyle`.
  conditionMarkers?: boolean;
  // The "Dot colour" field inside the Points card. Only meaningful with
  // `markerStyle`, and set to false on a plot whose renderer decides the colour
  // itself -- from the condition palette, or from a colour scale over the data.
  // `resolve_marker` in backend/app/services/plot_images.py reads `markerColor`
  // and then discards it in both cases, so the field would take a colour and
  // draw nothing with it.
  markerColor?: boolean;
  // Three classes of dot in one figure, each sized and faded on its own.
  volcanoMarkers?: boolean;
  // Colours that moved here out of a plot's own options row.
  barColor?: boolean;
  // Feature names written beside the rows of a heatmap (the ANOVA cluster
  // heatmaps, when their "Show feature names" option is on).
  rowLabels?: boolean;
  phosphoClassColors?: boolean;
  vennColors?: boolean;
  // The numbers drawn on bars and boxes.
  valueLabels?: boolean;
};

export type AdvancedPlotControlDefaults = Partial<
  Pick<
    AdvancedPlotSettings,
    | "axisLineTop"
    | "axisLineRight"
    | "axisLineBottom"
    | "axisLineLeft"
    | "axisLineColor"
    | "axisLineWidth"
    | "axisLineStyle"
    | "gridLineVisible"
    | "gridLineAxis"
    | "gridLineColor"
    | "gridLineWidth"
    | "gridLineStyle"
  >
>;

type Props = {
  value: AdvancedPlotSettings;
  onChange: (next: AdvancedPlotSettings) => void;
  conditionOptions?: string[];
  conditionDisplayLabels?: Record<string, string>;
  sampleOptions?: string[];
  sampleDisplayLabels?: Record<string, string>;
  visibleControls?: AdvancedPlotVisibleControls;
  controlDefaults?: AdvancedPlotControlDefaults;
};

const DEFAULT_VALUES = {
  titleSize: 12,
  axisLabelSize: 10,
  xTickLabelSize: 10,
  yTickLabelSize: 10,
  tickRotation: 0,
  legendFontSize: 10,
  offset: 0,
};

const inputClass =
  "mt-1 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-sky-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500";

// Mirrors MARKER_SHAPES in backend/app/services/plot_images.py. Every name here
// has a spelling in both matplotlib and plotly, so a shape chosen once draws the
// same marker in the figure and in the interactive plot beside it.
const MARKER_SHAPE_OPTIONS = [
  { value: "circle", label: "Circle" },
  { value: "square", label: "Square" },
  { value: "diamond", label: "Diamond" },
  { value: "triangle-up", label: "Triangle" },
  { value: "triangle-down", label: "Triangle (down)" },
  { value: "cross", label: "Cross" },
  { value: "x", label: "X" },
  { value: "star", label: "Star" },
  { value: "pentagon", label: "Pentagon" },
  { value: "hexagon", label: "Hexagon" },
];

// A general point setting and the per-condition map it governs. Choosing the
// general value clears the map, so every condition snaps to it; each can then
// be moved off it again, until the next general change.
const MARKER_OVERRIDE_MAPS = {
  markerSize: "conditionMarkerSizes",
  markerShape: "conditionMarkerShapes",
  markerAlpha: "conditionMarkerAlphas",
  markerEdgeWidth: "conditionMarkerEdgeWidths",
  markerEdgeColor: "conditionMarkerEdgeColors",
} as const;

const PLOT_THEME_OPTIONS = [
  { value: "default", label: "Default" },
  { value: "white", label: "White" },
  { value: "minimal", label: "Minimal" },
  { value: "soft_gray", label: "Soft gray" },
  { value: "presentation", label: "Presentation" },
  { value: "dark", label: "Dark" },
];

// Mirrors PLOT_FONTS in backend/app/services/plot_images.py. The faces actually
// installed are the Liberation family, whose metrics are identical to Arial,
// Helvetica, Times New Roman and Courier -- so a figure drawn in "Helvetica /
// Arial" measures the same as one a journal typeset in Arial.
const FONT_OPTIONS = [
  { value: "helvetica", label: "Helvetica / Arial" },
  { value: "times", label: "Times New Roman" },
  { value: "courier", label: "Courier" },
  { value: "dejavu-sans", label: "DejaVu Sans" },
  { value: "dejavu-serif", label: "DejaVu Serif" },
];

// The five texts that may disagree with the global font, and the key each one
// writes. Rendered as one card, because a font control repeated inside five
// other cards is five places to look for the same thing.
const FONT_ELEMENTS = [
  { key: "titleFontFamily", label: "Title" },
  { key: "axisLabelFontFamily", label: "Axis labels" },
  { key: "tickFontFamily", label: "Tick labels" },
  { key: "legendFontFamily", label: "Legend" },
  { key: "valueLabelFontFamily", label: "Value labels and annotations" },
] as const;

const AXIS_LINE_STYLE_OPTIONS = [
  { value: "solid", label: "Solid" },
  { value: "dashed", label: "Dashed" },
  { value: "dotted", label: "Dotted" },
  { value: "dashdot", label: "Dash dot" },
];

const GRID_LINE_AXIS_OPTIONS = [
  { value: "both", label: "Both" },
  { value: "x", label: "Vertical" },
  { value: "y", label: "Horizontal" },
];

function numberOrUndefined(value: string): number | undefined {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return undefined;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export default function AdvancedPlotOptions({
  value,
  onChange,
  conditionOptions = [],
  conditionDisplayLabels = {},
  sampleOptions = [],
  sampleDisplayLabels = {},
  visibleControls = {},
  controlDefaults = {},
}: Props) {
  const showTextElements = visibleControls.textElements !== false;
  const showTickControls = visibleControls.tickControls !== false;
  const showLegendControls = visibleControls.legendControls !== false;
  const showReferenceLineColor = visibleControls.referenceLineColor === true;
  const showReferenceLineToggle = visibleControls.referenceLineToggle !== false;
  const showReferenceLineLegend = visibleControls.referenceLineLegend === true;
  // Colour, style and width only while the line is drawn.
  const showReferenceLineLook = !showReferenceLineToggle || value.referenceLineVisible !== false;
  // Every plot has text in it, so this one is on unless a caller says otherwise.
  const showFontControls = visibleControls.fontControls !== false;
  const showConditionLabels = visibleControls.conditionLabels !== false;
  const showSampleLabels = visibleControls.sampleLabels !== false;
  const showConditionColors = visibleControls.conditionColors !== false;
  const showBoxplotStyle = visibleControls.boxplotStyle === true;
  const showBoxplotOutliers = visibleControls.boxplotOutliers === true;
  const showBoxplotPoints = visibleControls.boxplotPoints === true;
  const showMarkerStyle = visibleControls.markerStyle === true;
  const showConditionMarkers =
    visibleControls.conditionMarkers === true && conditionOptions.length > 0;
  const showMarkerColor = visibleControls.markerColor !== false;
  const showVolcanoMarkers = visibleControls.volcanoMarkers === true;
  const showBarColor = visibleControls.barColor === true;
  const showRowLabels = visibleControls.rowLabels === true;
  const showPhosphoClassColors = visibleControls.phosphoClassColors === true;
  const showVennColors = visibleControls.vennColors === true;
  const showValueLabels = visibleControls.valueLabels === true;
  const showCorrelationGradient = visibleControls.correlationGradient === true;
  const showBackgroundControls = visibleControls.backgroundControls !== false;
  const showAxisLineControls = visibleControls.axisLineControls !== false;
  // The last fallback is matplotlib's own figure, for a page that passes no
  // defaults; every page does, from lib/plotControlDefaults.ts.
  const axisLineLeft = value.axisLineLeft ?? controlDefaults.axisLineLeft ?? true;
  const axisLineRight = value.axisLineRight ?? controlDefaults.axisLineRight ?? true;
  const axisLineBottom = value.axisLineBottom ?? controlDefaults.axisLineBottom ?? true;
  const axisLineTop = value.axisLineTop ?? controlDefaults.axisLineTop ?? true;
  const axisLineColor = value.axisLineColor ?? controlDefaults.axisLineColor ?? "#000000";
  const axisLineWidth = value.axisLineWidth ?? controlDefaults.axisLineWidth ?? 0.8;
  const axisLineStyle = value.axisLineStyle ?? controlDefaults.axisLineStyle ?? "solid";
  const gridLineVisible = value.gridLineVisible ?? controlDefaults.gridLineVisible ?? false;
  const gridLineAxis = value.gridLineAxis ?? controlDefaults.gridLineAxis ?? "y";
  const gridLineColor = value.gridLineColor ?? controlDefaults.gridLineColor ?? "#b0b0b0";
  const gridLineWidth = value.gridLineWidth ?? controlDefaults.gridLineWidth ?? 0.8;
  const gridLineStyle = value.gridLineStyle ?? controlDefaults.gridLineStyle ?? "solid";

  // Only what the user changed is stored, and so only that is sent. This used
  // to add every displayed frame and grid value to the first edit of anything
  // -- a title edit also sent a grid colour -- and because the displayed values
  // are not what every plot draws, that first edit changed the plot in places
  // nobody had touched, and switching advanced mode on re-applied them.
  function patch(next: Partial<AdvancedPlotSettings>) {
    onChange({ ...value, ...next });
  }

  /** A general point setting, which resets every per-condition override of it.
   *
   * This is the whole behaviour of the card: set the general size and all groups
   * become that size; set one group and only it moves; set the general size
   * again and they all snap back together. The volcano's three significance
   * classes are the same idea with fixed names, so its class values are cleared
   * by the same act.
   */
  function patchGeneralMarker(next: Partial<AdvancedPlotSettings>) {
    const cleared: Partial<AdvancedPlotSettings> = {};
    for (const key of Object.keys(next) as (keyof typeof MARKER_OVERRIDE_MAPS)[]) {
      const mapKey = MARKER_OVERRIDE_MAPS[key];
      if (mapKey) cleared[mapKey] = {};
    }
    if (showVolcanoMarkers) {
      if ("markerSize" in next) {
        cleared.volcanoUpSize = undefined;
        cleared.volcanoDownSize = undefined;
        cleared.volcanoNsSize = undefined;
      }
      if ("markerAlpha" in next) {
        cleared.volcanoUpAlpha = undefined;
        cleared.volcanoDownAlpha = undefined;
        cleared.volcanoNsAlpha = undefined;
      }
    }
    patch({ ...cleared, ...next });
  }

  /** One condition's override of one point setting. `undefined` removes it. */
  function patchConditionMarker(
    mapKey: (typeof MARKER_OVERRIDE_MAPS)[keyof typeof MARKER_OVERRIDE_MAPS],
    condition: string,
    entry: number | string | undefined
  ) {
    const current = { ...((value[mapKey] ?? {}) as Record<string, number | string>) };
    if (entry === undefined || entry === "") delete current[condition];
    else current[condition] = entry;
    patch({ [mapKey]: current } as Partial<AdvancedPlotSettings>);
  }

  // One row per condition, rendered inside whichever card holds this plot's
  // point controls -- the Points card on a scatter, the boxes card on a
  // single-protein boxplot, whose jittered points are its points.
  const conditionMarkerRows = showConditionMarkers ? (
          <div className="mt-5 border-t border-slate-200 pt-4 dark:border-slate-700">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Per condition
            </p>
            <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
              Empty means "use the setting above". Changing a setting above puts every
              condition back on it.
            </p>
            <div className="mt-3 space-y-3">
              {conditionOptions.map((condition) => (
                <div
                  key={condition}
                  className="grid items-end gap-3 rounded-xl border border-slate-200 p-3 lg:grid-cols-[10rem_repeat(4,1fr)] dark:border-slate-700"
                >
                  <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {conditionDisplayLabels[condition] || condition}
                  </div>
                  <label className="block">
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">Shape</span>
                    <AssistantSelect data-assistant-permission="view"
                      value={String(value.conditionMarkerShapes?.[condition] ?? "")}
                      onChange={(event) =>
                        patchConditionMarker(
                          "conditionMarkerShapes",
                          condition,
                          event.target.value || undefined
                        )
                      }
                      className={inputClass}
                    >
                      <option value="">Same as above</option>
                      {MARKER_SHAPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </AssistantSelect>
                  </label>
                  <label className="block">
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">Size</span>
                    <NumberInput
                      min="0.5"
                      step="0.5"
                      value={value.conditionMarkerSizes?.[condition]}
                      fallback={undefined}
                      onValidChange={(next) =>
                        patchConditionMarker("conditionMarkerSizes", condition, next)
                      }
                    />
                  </label>
                  <label className="block">
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">Opacity</span>
                    <NumberInput
                      min="0"
                      max="1"
                      step="0.05"
                      value={value.conditionMarkerAlphas?.[condition]}
                      fallback={undefined}
                      onValidChange={(next) =>
                        patchConditionMarker("conditionMarkerAlphas", condition, next)
                      }
                    />
                  </label>
                  <label className="block">
                    <span className="text-[11px] text-slate-500 dark:text-slate-400">Outline width</span>
                    <NumberInput
                      min="0"
                      step="0.1"
                      value={value.conditionMarkerEdgeWidths?.[condition]}
                      fallback={undefined}
                      onValidChange={(next) =>
                        patchConditionMarker("conditionMarkerEdgeWidths", condition, next)
                      }
                    />
                  </label>
                </div>
              ))}
            </div>
          </div>
  ) : null;

  /** Which sides of the frame are drawn.
   *
   * The four sides are one decision and travel together, because a renderer
   * cannot tell "top unticked, others untouched" from "top unticked, others
   * off" without them. Drawing a side that was not drawn also sends the colour,
   * width and style the panel shows, so the new line looks as displayed rather
   * than taking the renderer's own -- which on Plotly is a white line on a pale
   * background. Hiding a side sends nothing else.
   */
  function patchFrameSides(
    next: Partial<Pick<AdvancedPlotSettings, "axisLineLeft" | "axisLineRight" | "axisLineBottom" | "axisLineTop">>
  ) {
    const current = { axisLineLeft, axisLineRight, axisLineBottom, axisLineTop };
    const drawsNewSide = (Object.keys(next) as (keyof typeof current)[]).some(
      (side) => next[side] === true && !current[side]
    );
    patch({
      ...current,
      ...next,
      ...(drawsNewSide ? { axisLineColor, axisLineWidth, axisLineStyle } : {}),
    });
  }

  /** Frame colour, width or style: each on its own. */
  function patchFrameLook(
    next: Partial<Pick<AdvancedPlotSettings, "axisLineColor" | "axisLineWidth" | "axisLineStyle">>
  ) {
    patch(next);
  }

  /** Where the grid is: whether there is one, and on which axes.
   *
   * A pair, for the same reason as the frame sides. Switching a grid on sends
   * the colour, width and style the panel shows, so it is drawn as displayed.
   */
  function patchGridPlacement(
    next: Partial<Pick<AdvancedPlotSettings, "gridLineVisible" | "gridLineAxis">>
  ) {
    const placement = { gridLineVisible, gridLineAxis, ...next };
    const switchesOn = placement.gridLineVisible === true && !gridLineVisible;
    patch({
      ...placement,
      ...(switchesOn ? { gridLineColor, gridLineWidth, gridLineStyle } : {}),
    });
  }

  /** Grid colour, width or style. On a plot with a grid, that one setting and
   * nothing else. On a plot without one, editing how the grid looks is asking
   * for it, so the grid is switched on in the look the panel shows.
   */
  function patchGridLook(
    next: Partial<Pick<AdvancedPlotSettings, "gridLineColor" | "gridLineWidth" | "gridLineStyle">>
  ) {
    if (gridLineVisible) {
      patch(next);
      return;
    }
    patch({
      gridLineVisible: true,
      gridLineAxis,
      gridLineColor,
      gridLineWidth,
      gridLineStyle,
      ...next,
    });
  }

  function patchElement(key: ElementKey, next: Partial<AdvancedTextElementSettings>) {
    patch({ [key]: { ...(value[key] ?? {}), ...next } } as Partial<AdvancedPlotSettings>);
  }

  function patchMap(
    key: "conditionLabels" | "sampleLabels" | "conditionColors",
    mapKey: string,
    mapValue: string,
  ) {
    const current = value[key] ?? {};
    const next = { ...current };
    if (mapValue.trim()) {
      next[mapKey] = mapValue;
    } else {
      delete next[mapKey];
    }
    patch({ [key]: next } as Partial<AdvancedPlotSettings>);
  }

  return (
    <section data-assistant-appearance="true" className="rounded-2xl border border-sky-200 bg-sky-50/70 p-5 shadow-sm dark:border-sky-500/30 dark:bg-sky-500/10">
      <div className="text-xs font-semibold uppercase tracking-[0.22em] text-sky-700 dark:text-sky-300">
        Advanced Plot Options
      </div>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
        One card per plot element. Open the one you want to change; the rest stay
        out of the way.
      </p>

      <div className="mt-4 space-y-2">
        {showFontControls ? (
          <Section title="Font" summary="One face for the whole figure, or one per text">
            <label className="block max-w-xs">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">All text</span>
              <AssistantSelect data-assistant-permission="view"
                value={value.fontFamily || ""}
                onChange={(event) => patch({ fontFamily: event.target.value })}
                className={inputClass}
              >
                <option value="">Plot default</option>
                {FONT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </AssistantSelect>
            </label>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FONT_ELEMENTS.map((element) => (
                <label className="block" key={element.key}>
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                    {element.label}
                  </span>
                  <AssistantSelect data-assistant-permission="view"
                    value={value[element.key] || ""}
                    onChange={(event) => patch({ [element.key]: event.target.value })}
                    className={inputClass}
                  >
                    <option value="">Same as all text</option>
                    {FONT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </AssistantSelect>
                </label>
              ))}
            </div>
          </Section>
        ) : null}

        {showTextElements ? (
          <Section title="Title" summary="Show, text, size, weight, color, position">
            <label className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <AssistantInput data-assistant-permission="view"
                type="checkbox"
                checked={value.titleVisible ?? true}
                onChange={(event) => patch({ titleVisible: event.target.checked })}
                className="h-4 w-4"
              />
              Show title
            </label>
            <TextElementCard
              title="Title"
              placeholder="Overwrite plot title"
              defaultSize={DEFAULT_VALUES.titleSize}
              value={value.titleElement}
              onChange={(next) => patchElement("titleElement", next)}
            />
          </Section>
        ) : null}

        {showTextElements || showTickControls ? (
          <Section title="X axis" summary="Axis label and tick labels">
            <div className="space-y-3">
              {showTextElements ? (
                <TextElementCard
                  title="Axis label"
                  placeholder="Overwrite x-axis label"
                  defaultSize={DEFAULT_VALUES.axisLabelSize}
                  value={value.xLabelElement}
                  onChange={(next) => patchElement("xLabelElement", next)}
                />
              ) : null}
              {showTickControls ? (
                <TickRow
                  axis="X"
                  size={value.xTickLabelSize}
                  rotation={value.xTickLabelRotation}
                  color={value.xTickLabelColor}
                  defaultSize={DEFAULT_VALUES.xTickLabelSize}
                  onSize={(next) => patch({ xTickLabelSize: next })}
                  onRotation={(next) => patch({ xTickLabelRotation: next })}
                  onColor={(next) => patch({ xTickLabelColor: next })}
                />
              ) : null}
            </div>
          </Section>
        ) : null}

        {showTextElements || showTickControls ? (
          <Section title="Y axis" summary="Axis label and tick labels">
            <div className="space-y-3">
              {showTextElements ? (
                <TextElementCard
                  title="Axis label"
                  placeholder="Overwrite y-axis label"
                  defaultSize={DEFAULT_VALUES.axisLabelSize}
                  value={value.yLabelElement}
                  onChange={(next) => patchElement("yLabelElement", next)}
                />
              ) : null}
              {showTickControls ? (
                <TickRow
                  axis="Y"
                  size={value.yTickLabelSize}
                  rotation={value.yTickLabelRotation}
                  color={value.yTickLabelColor}
                  defaultSize={DEFAULT_VALUES.yTickLabelSize}
                  onSize={(next) => patch({ yTickLabelSize: next })}
                  onRotation={(next) => patch({ yTickLabelRotation: next })}
                  onColor={(next) => patch({ yTickLabelColor: next })}
                />
              ) : null}
            </div>
          </Section>
        ) : null}

        {showLegendControls ? (
          <Section title="Legend" summary="Show, title, size, color, frame, position">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label className="flex items-center gap-2 self-end pb-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <AssistantInput data-assistant-permission="view"
                  type="checkbox"
                  checked={value.legendVisible ?? true}
                  onChange={(event) => patch({ legendVisible: event.target.checked })}
                  className="h-4 w-4"
                />
                Show legend
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Legend title</span>
                <AssistantInput data-assistant-permission="view"
                  type="text"
                  value={value.legendTitle ?? ""}
                  placeholder="Keep the plot's own title"
                  onChange={(event) => patch({ legendTitle: event.target.value })}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Text size</span>
                <NumberInput
                  value={value.legendFontSize ?? DEFAULT_VALUES.legendFontSize}
                  fallback={DEFAULT_VALUES.legendFontSize}
                  onValidChange={(next) => patch({ legendFontSize: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Text color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.legendTextColor || "#111827"}
                  onChange={(event) => patch({ legendTextColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="flex items-center gap-2 self-end pb-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <AssistantInput data-assistant-permission="view"
                  type="checkbox"
                  checked={value.legendFrame ?? false}
                  onChange={(event) => patch({ legendFrame: event.target.checked })}
                  className="h-4 w-4"
                />
                Draw a frame
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Offset x / y (px)</span>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  <NumberInput
                    step="1"
                    value={value.legendXOffset ?? DEFAULT_VALUES.offset}
                    ariaLabel="Legend X offset (px)"
                    fallback={DEFAULT_VALUES.offset}
                    className={inputClass.replace("mt-1 ", "")}
                    onValidChange={(next) => patch({ legendXOffset: next })}
                  />
                  <NumberInput
                    step="1"
                    value={value.legendYOffset ?? DEFAULT_VALUES.offset}
                    ariaLabel="Legend Y offset (px)"
                    fallback={DEFAULT_VALUES.offset}
                    className={inputClass.replace("mt-1 ", "")}
                    onValidChange={(next) => patch({ legendYOffset: next })}
                  />
                </div>
              </label>
            </div>
          </Section>
        ) : null}

        {showAxisLineControls ? (
          <Section title="Frame and grid" summary="Which sides are drawn, and the grid behind the data">
            <div className="space-y-4">
            <div data-assistant-group="Axis frame">
            <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Axis frame</div>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div>
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Sides</span>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <AssistantInput data-assistant-permission="view"
                      type="checkbox"
                      checked={axisLineLeft}
                      onChange={(event) => patchFrameSides({ axisLineLeft: event.target.checked })}
                      className="h-4 w-4 accent-sky-600"
                    />
                    Left
                  </label>
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <AssistantInput data-assistant-permission="view"
                      type="checkbox"
                      checked={axisLineRight}
                      onChange={(event) => patchFrameSides({ axisLineRight: event.target.checked })}
                      className="h-4 w-4 accent-sky-600"
                    />
                    Right
                  </label>
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <AssistantInput data-assistant-permission="view"
                      type="checkbox"
                      checked={axisLineBottom}
                      onChange={(event) => patchFrameSides({ axisLineBottom: event.target.checked })}
                      className="h-4 w-4 accent-sky-600"
                    />
                    Bottom
                  </label>
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                    <AssistantInput data-assistant-permission="view"
                      type="checkbox"
                      checked={axisLineTop}
                      onChange={(event) => patchFrameSides({ axisLineTop: event.target.checked })}
                      className="h-4 w-4 accent-sky-600"
                    />
                    Top
                  </label>
                </div>
              </div>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={isHexColor(axisLineColor) ? axisLineColor : "#000000"}
                  onChange={(event) => patchFrameLook({ axisLineColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Width</span>
                <NumberInput
                  min="0"
                  step="0.5"
                  value={axisLineWidth}
                  fallback={1}
                  onValidChange={(next) => patchFrameLook({ axisLineWidth: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Style</span>
                <AssistantSelect data-assistant-permission="view"
                  value={axisLineStyle}
                  onChange={(event) => patchFrameLook({ axisLineStyle: event.target.value })}
                  className={inputClass}
                >
                  {AXIS_LINE_STYLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </AssistantSelect>
              </label>
            </div>
          </div>
          <div data-assistant-group="Grid lines">
          <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Grid lines</div>
          <div className="mt-3 grid gap-3 sm:grid-cols-5">
            <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <AssistantInput data-assistant-permission="view"
                type="checkbox"
                checked={gridLineVisible}
                onChange={(event) => patchGridPlacement({ gridLineVisible: event.target.checked })}
                className="h-4 w-4 accent-sky-600"
              />
              Show
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Direction</span>
              <AssistantSelect data-assistant-permission="view"
                value={gridLineAxis}
                onChange={(event) => patchGridPlacement({ gridLineAxis: event.target.value, gridLineVisible: true })}
                className={inputClass}
              >
                {GRID_LINE_AXIS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </AssistantSelect>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
              <AssistantInput data-assistant-permission="view"
                type="color"
                value={isHexColor(gridLineColor) ? gridLineColor : "#b0b0b0"}
                onChange={(event) => patchGridLook({ gridLineColor: event.target.value })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Width</span>
              <NumberInput
                min="0"
                step="0.5"
                value={gridLineWidth}
                fallback={0.8}
                onValidChange={(next) => patchGridLook({ gridLineWidth: next })}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Style</span>
              <AssistantSelect data-assistant-permission="view"
                value={gridLineStyle}
                onChange={(event) => patchGridLook({ gridLineStyle: event.target.value })}
                className={inputClass}
              >
                {AXIS_LINE_STYLE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </AssistantSelect>
            </label>
          </div>
          </div>
            </div>
          </Section>
        ) : null}

        {showBackgroundControls ? (
          <Section title="Background" summary="Theme, color, transparency">
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Theme</span>
                <AssistantSelect data-assistant-permission="view"
                  value={value.plotTheme || "default"}
                  onChange={(event) => patch({ plotTheme: event.target.value })}
                  className={inputClass}
                >
                  {PLOT_THEME_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </AssistantSelect>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={isHexColor(value.backgroundColor || "") ? value.backgroundColor : "#ffffff"}
                  onChange={(event) => patch({ backgroundColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <AssistantInput data-assistant-permission="view"
                  type="checkbox"
                  checked={Boolean(value.transparentBackground)}
                  onChange={(event) => patch({ transparentBackground: event.target.checked })}
                  className="h-4 w-4 accent-sky-600"
                />
                Transparent
              </label>
            </div>
          </Section>
        ) : null}

        {showReferenceLineColor ? (
          <Section
            title="Reference line"
            summary="The threshold, fit and guide lines drawn over the data"
          >
            <div className="grid gap-3 sm:grid-cols-4">
              {showReferenceLineToggle ? (
              <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <AssistantInput data-assistant-permission="view"
                  type="checkbox"
                  checked={value.referenceLineVisible !== false}
                  onChange={(event) => patch({ referenceLineVisible: event.target.checked })}
                  className="h-4 w-4 accent-sky-600"
                />
                Show
              </label>
              ) : null}
              {showReferenceLineLegend ? (
              <label className="mt-6 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <AssistantInput data-assistant-permission="view"
                  type="checkbox"
                  checked={value.referenceLineLegend !== false}
                  onChange={(event) => patch({ referenceLineLegend: event.target.checked })}
                  className="h-4 w-4 accent-sky-600"
                />
                Legend entry
              </label>
              ) : null}
              {showReferenceLineLook ? (
              <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.referenceLineColor || "#ff0000"}
                  onChange={(event) => patch({ referenceLineColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Style</span>
                <AssistantSelect data-assistant-permission="view"
                  value={value.referenceLineStyle || "dashed"}
                  onChange={(event) => patch({ referenceLineStyle: event.target.value })}
                  className={inputClass}
                >
                  {AXIS_LINE_STYLE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </AssistantSelect>
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Width</span>
                <NumberInput
                  min="0"
                  step="0.5"
                  value={value.referenceLineWidth ?? 1.5}
                  fallback={1.5}
                  onValidChange={(next) => patch({ referenceLineWidth: next })}
                />
              </label>
              </>
              ) : null}
            </div>
          </Section>
        ) : null}

        {showMarkerStyle ? (
          <Section
            title="Points"
            summary={
              [
                showMarkerColor ? "Color, shape, size and outline" : "Shape, size and outline",
                showConditionMarkers ? ", for all dots or one condition" : "",
              ].join("")
            }
          >
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          {showMarkerColor ? (
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot color</span>
              <AssistantInput data-assistant-permission="view"
                type="color"
                value={value.markerColor || "#1f77b4"}
                onChange={(event) => patchGeneralMarker({ markerColor: event.target.value })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
          ) : null}
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot size (pt)</span>
            <NumberInput
              min="0.5"
              step="0.5"
              value={value.markerSize ?? 6}
              fallback={6}
              onValidChange={(next) => patchGeneralMarker({ markerSize: next })}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot opacity (0-1)</span>
            <NumberInput
              min="0"
              max="1"
              step="0.05"
              value={value.markerAlpha ?? 0.8}
              fallback={0.8}
              onValidChange={(next) => patchGeneralMarker({ markerAlpha: next })}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot outline color</span>
            <AssistantInput data-assistant-permission="view"
              type="color"
              value={value.markerEdgeColor || "#000000"}
              onChange={(event) => patchGeneralMarker({ markerEdgeColor: event.target.value })}
              className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot outline width (0 = none)</span>
            <NumberInput
              min="0"
              step="0.1"
              value={value.markerEdgeWidth ?? 0}
              fallback={0}
              onValidChange={(next) => patchGeneralMarker({ markerEdgeWidth: next })}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Dot shape</span>
            <AssistantSelect data-assistant-permission="view"
              value={value.markerShape ?? "circle"}
              onChange={(event) => patchGeneralMarker({ markerShape: event.target.value })}
              className={inputClass}
            >
              {MARKER_SHAPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </AssistantSelect>
          </label>
        </div>
        {conditionMarkerRows}
          </Section>
        ) : null}

        {showVolcanoMarkers ? (
          <Section
            title="Volcano points"
            summary="All three classes at once, then each on its own"
          >
        <div className="mt-4 space-y-3">
          <div className="grid gap-4 rounded-xl border border-slate-200 p-3 lg:grid-cols-4 dark:border-slate-700">
            <span className="self-center text-xs font-semibold text-slate-600 dark:text-slate-300">
              All classes
            </span>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size</span>
              <NumberInput
                min="0.5"
                step="0.5"
                value={value.markerSize ?? 6}
                fallback={6}
                onValidChange={(next) => patchGeneralMarker({ markerSize: next })}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Opacity</span>
              <NumberInput
                min="0"
                max="1"
                step="0.05"
                value={value.markerAlpha ?? 0.85}
                fallback={0.85}
                onValidChange={(next) => patchGeneralMarker({ markerAlpha: next })}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Shape</span>
              <AssistantSelect data-assistant-permission="view"
                value={value.markerShape ?? "circle"}
                onChange={(event) => patchGeneralMarker({ markerShape: event.target.value })}
                className={inputClass}
              >
                {MARKER_SHAPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </AssistantSelect>
            </label>
          </div>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">
            Setting a size or opacity above puts all three classes back on it. Below,
            each class can then be moved off it again.
          </p>
          {([
            ["Up-regulated", "volcanoUpSize", "volcanoUpAlpha", "volcanoUpColor", 6, 0.85, "#b2182b"],
            ["Down-regulated", "volcanoDownSize", "volcanoDownAlpha", "volcanoDownColor", 6, 0.85, "#2166ac"],
            ["Not significant", "volcanoNsSize", "volcanoNsAlpha", "volcanoNsColor", 5, 0.55, "#bdbdbd"],
          ] as const).map(([label, sizeKey, alphaKey, colorKey, sizeDefault, alphaDefault, colorDefault]) => (
            <div key={sizeKey} className="grid gap-4 lg:grid-cols-4">
              <span className="self-center text-xs font-semibold text-slate-600 dark:text-slate-300">
                {label}
              </span>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size</span>
                <NumberInput
                  min="0.5"
                  step="0.5"
                  value={value[sizeKey] ?? value.markerSize ?? sizeDefault}
                  fallback={value.markerSize ?? sizeDefault}
                  onValidChange={(next) => patch({ [sizeKey]: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Opacity</span>
                <NumberInput
                  min="0"
                  max="1"
                  step="0.05"
                  value={value[alphaKey] ?? value.markerAlpha ?? alphaDefault}
                  fallback={value.markerAlpha ?? alphaDefault}
                  onValidChange={(next) => patch({ [alphaKey]: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value[colorKey] || colorDefault}
                  onChange={(event) => patch({ [colorKey]: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
            </div>
          ))}
          <div className="grid gap-4 lg:grid-cols-4">
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Highlight size</span>
              <NumberInput
                min="0.5"
                step="0.5"
                value={value.volcanoHighlightSize ?? 10}
                fallback={10}
                onValidChange={(next) => patch({ volcanoHighlightSize: next })}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Highlight outline</span>
              <AssistantInput data-assistant-permission="view"
                type="color"
                value={value.volcanoHighlightColor || "#22c55e"}
                onChange={(event) => patch({ volcanoHighlightColor: event.target.value })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Hit label size (static plot)</span>
              <NumberInput
                min="3"
                step="0.5"
                value={value.volcanoLabelSize ?? 7}
                fallback={7}
                onValidChange={(next) => patch({ volcanoLabelSize: next })}
              />
            </label>
          </div>
        </div>
          </Section>
        ) : null}

        {showBoxplotStyle ? (
          <Section title="Boxes and their points" summary="Box, median, data points, outliers">
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Box border color</span>
            <AssistantInput data-assistant-permission="view"
              type="color"
              value={value.boxBorderColor || "#000000"}
              onChange={(event) => patch({ boxBorderColor: event.target.value })}
              className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Median color</span>
            <AssistantInput data-assistant-permission="view"
              type="color"
              value={value.boxMedianColor || "#b22222"}
              onChange={(event) => patch({ boxMedianColor: event.target.value })}
              className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
            />
          </label>
          {showBoxplotPoints ? (
            <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Data dot size (pt)</span>
                <NumberInput
                  min="0.5"
                  step="0.5"
                  value={value.boxPointSize ?? 4.5}
                  fallback={4.5}
                  onValidChange={(next) => patch({ boxPointSize: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Data dot opacity</span>
                <NumberInput
                  min="0"
                  max="1"
                  step="0.05"
                  value={value.boxPointAlpha ?? 0.8}
                  fallback={0.8}
                  onValidChange={(next) => patch({ boxPointAlpha: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Data dot outline</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.boxPointEdgeColor || "#000000"}
                  onChange={(event) => patch({ boxPointEdgeColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Data dot outline width (0 = none)</span>
                <NumberInput
                  min="0"
                  step="0.1"
                  value={value.boxPointEdgeWidth ?? 0.4}
                  fallback={0.4}
                  onValidChange={(next) => patch({ boxPointEdgeWidth: next })}
                />
              </label>
            </>
          ) : null}
          {showBoxplotOutliers ? (
            <>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier dot color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.boxOutlierColor || "#ff0000"}
                  onChange={(event) => patch({ boxOutlierColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier outline color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.boxOutlierEdgeColor || "#000000"}
                  onChange={(event) => patch({ boxOutlierEdgeColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Outlier size (pt)</span>
                <NumberInput
                  min="1"
                  step="1"
                  value={value.boxOutlierSize ?? 5}
                  fallback={5}
                  onValidChange={(next) => patch({ boxOutlierSize: next })}
                />
              </label>
            </>
          ) : null}
        </div>
        {showBoxplotPoints ? conditionMarkerRows : null}
          </Section>
        ) : null}

        {showBarColor ? (
          <Section title="Bars" summary="Bar color">
            <label className="block max-w-xs">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Bar color</span>
              <AssistantInput data-assistant-permission="view"
                type="color"
                value={value.barColor || "#2563eb"}
                onChange={(event) => patch({ barColor: event.target.value })}
                className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
              />
            </label>
          </Section>
        ) : null}

        {showPhosphoClassColors ? (
          <Section title="Site classes" summary="Color of each localization class">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Class I</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.classIColor || "#2563eb"}
                  onChange={(event) => patch({ classIColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Not Class I</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.classNotIColor || "#94a3b8"}
                  onChange={(event) => patch({ classNotIColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
            </div>
          </Section>
        ) : null}

        {showVennColors ? (
          <Section title="Venn sets" summary="One color per set">
            <div className="grid gap-3 sm:grid-cols-3">
              {([
                ["Set 1", "vennColor1", "#2563eb"],
                ["Set 2", "vennColor2", "#f97316"],
                ["Set 3", "vennColor3", "#16a34a"],
              ] as const).map(([label, key, fallback]) => (
                <label key={key} className="block">
                  <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">{label}</span>
                  <AssistantInput data-assistant-permission="view"
                    type="color"
                    value={value[key] || fallback}
                    onChange={(event) => patch({ [key]: event.target.value })}
                    className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                </label>
              ))}
            </div>
          </Section>
        ) : null}

        {showValueLabels ? (
          <Section title="Value labels" summary="Size of the numbers drawn on the marks">
            <label className="block max-w-xs">
              <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Label size</span>
              <NumberInput
                min="4"
                step="1"
                value={value.valueLabelSize ?? 8}
                fallback={8}
                onValidChange={(next) => patch({ valueLabelSize: next })}
              />
            </label>
          </Section>
        ) : null}

        {showRowLabels ? (
          <Section title="Row labels" summary="Size and color of the feature names beside the rows">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size (empty = fit to rows)</span>
                <NumberInput
                  min="1"
                  step="0.5"
                  value={value.rowLabelSize}
                  fallback={undefined}
                  ariaLabel="Row label size"
                  onValidChange={(next) => patch({ rowLabelSize: next })}
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
                <AssistantInput data-assistant-permission="view"
                  type="color"
                  value={value.rowLabelColor || "#000000"}
                  onChange={(event) => patch({ rowLabelColor: event.target.value })}
                  className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
                />
              </label>
            </div>
          </Section>
        ) : null}

        {showCorrelationGradient ? (
          <Section title="Color scale" summary="The gradient the matrix is painted with">
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <label className="block">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Correlation gradient</span>
            <AssistantSelect data-assistant-permission="view"
              value={value.correlationColorMap || "coolwarm"}
              onChange={(event) => patch({ correlationColorMap: event.target.value })}
              className={inputClass}
            >
              <option value="coolwarm">Coolwarm</option>
              <option value="RdBu_r">Red/blue</option>
              <option value="Spectral">Spectral</option>
              <option value="PiYG">Pink/green</option>
              <option value="PRGn">Purple/green</option>
              <option value="BrBG">Brown/teal</option>
              <option value="viridis">Viridis</option>
              <option value="cividis">Cividis</option>
            </AssistantSelect>
          </label>
        </div>
          </Section>
        ) : null}

        {showConditionLabels || showSampleLabels || showConditionColors ? (
          <Section title="Names and colors" summary="Rename conditions or samples, recolor groups">
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {showConditionLabels && conditionOptions.length ? (
            <KnownOverrideRows
              title="Condition names"
              items={conditionOptions}
              values={value.conditionLabels}
              placeholderSuffix="display name"
              displayLabels={conditionDisplayLabels}
              onChange={(key, nextValue) => patchMap("conditionLabels", key, nextValue)}
            />
          ) : null}
          {showSampleLabels && sampleOptions.length ? (
            <KnownOverrideRows
              title="Sample names"
              items={sampleOptions}
              values={value.sampleLabels}
              placeholderSuffix="new display name"
              displayLabels={sampleDisplayLabels}
              onChange={(key, nextValue) => patchMap("sampleLabels", key, nextValue)}
            />
          ) : null}
          {showConditionColors && conditionOptions.length ? (
            <KnownOverrideRows
              title="Condition colors"
              items={conditionOptions}
              values={value.conditionColors}
              placeholderSuffix="#hex color"
              inputType="colorText"
              onChange={(key, nextValue) => patchMap("conditionColors", key, nextValue)}
            />
          ) : null}
        </div>
          </Section>
        ) : null}
      </div>
    </section>
  );
}


/**
 * One plot element, collapsed until it is wanted.
 *
 * The panel holds every cosmetic control the renderers understand, which is far
 * more than fits on a screen at once. Grouping by element and starting closed
 * means the list of things you *could* change stays one line each, and opening
 * one puts every control for that element in front of you rather than scattered
 * between a "text" section and a "ticks" section.
 *
 * `<details>` rather than React state: it is keyboard accessible, it is
 * findable by the browser's own search, and it keeps its own open/closed state
 * without a re-render.
 */
function Section({
  title,
  summary,
  children,
}: {
  title: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <details
      data-assistant-group={title}
      className="group overflow-hidden rounded-2xl border border-slate-200 bg-white/85 dark:border-slate-700 dark:bg-slate-900/70"
    >
      <summary className="flex cursor-pointer select-none items-center gap-3 px-4 py-3 marker:content-[''] hover:bg-slate-50 dark:hover:bg-slate-800/60">
        <span
          aria-hidden="true"
          className="text-slate-400 transition-transform group-open:rotate-90 dark:text-slate-500"
        >
          ▸
        </span>
        <span className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</span>
        <span className="truncate text-xs text-slate-500 dark:text-slate-400">{summary}</span>
      </summary>
      <div className="border-t border-slate-200 px-4 py-4 dark:border-slate-700">{children}</div>
    </details>
  );
}

/** The tick labels of one axis, beside that axis's own label. */
function TickRow({
  axis,
  size,
  rotation,
  color,
  defaultSize,
  onSize,
  onRotation,
  onColor,
}: {
  axis: string;
  size: number | undefined;
  rotation: number | undefined;
  color: string | undefined;
  defaultSize: number;
  onSize: (next: number | undefined) => void;
  onRotation: (next: number | undefined) => void;
  onColor: (next: string) => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">Tick labels</div>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size</span>
          <NumberInput
            value={size ?? defaultSize}
            fallback={defaultSize}
            ariaLabel={`${axis} tick label size`}
            onValidChange={onSize}
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Rotation (deg)</span>
          <NumberInput
            step="1"
            value={rotation ?? DEFAULT_VALUES.tickRotation}
            fallback={DEFAULT_VALUES.tickRotation}
            ariaLabel={`${axis} tick label rotation`}
            onValidChange={onRotation}
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
          <AssistantInput data-assistant-permission="view"
            type="color"
            value={color || "#111827"}
            aria-label={`${axis} tick label color`}
            onChange={(event) => onColor(event.target.value)}
            className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
          />
        </label>
      </div>
    </div>
  );
}

function KnownOverrideRows({
  title,
  items,
  values,
  placeholderSuffix,
  displayLabels,
  inputType = "text",
  onChange,
}: {
  title: string;
  items: string[];
  values: Record<string, string> | undefined;
  placeholderSuffix: string;
  displayLabels?: Record<string, string>;
  inputType?: "text" | "colorText";
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div data-assistant-group={title} className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</div>
      <div className="mt-3 max-h-64 space-y-2 overflow-auto pr-1">
        {items.map((item) => {
          const current = values?.[item] ?? "";
          const displayLabel = displayLabels?.[item]?.trim();
          const placeholder = displayLabel || `${item} ${placeholderSuffix}`;
          return (
            <label key={item} className="grid gap-2 rounded-xl bg-slate-50 p-2 dark:bg-slate-800/80">
              <span className="break-words text-xs font-semibold text-slate-600 dark:text-slate-300">
                {item}
              </span>
              <div className="flex gap-2">
                {inputType === "colorText" ? (
                  <AssistantInput data-assistant-permission="view"
                    type="color"
                    value={isHexColor(current) ? current : "#64748b"}
                    onChange={(event) => onChange(item, event.target.value)}
                    className="h-10 w-12 rounded-lg border border-slate-300 bg-white px-1 dark:border-slate-600 dark:bg-slate-900"
                  />
                ) : null}
                <AssistantInput data-assistant-permission="view"
                  // The assistant names a sample by what the plot shows ("GRK_1"), not by
                  // its 90-character raw column header (2026-10-13: ten such names in every
                  // planner call).
                  aria-label={displayLabel && displayLabel !== item ? displayLabel : undefined}
                  value={current}
                  onChange={(event) => onChange(item, event.target.value)}
                  placeholder={placeholder}
                  className={inputClass.replace("mt-1 ", "")}
                />
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}


function TextElementCard({
  title,
  placeholder,
  defaultSize,
  // Absent until the user types into the card: the panel stores only what was
  // changed, so an untouched title has no element object at all.
  value = {},
  onChange,
}: {
  title: string;
  placeholder: string;
  defaultSize: number;
  value?: AdvancedTextElementSettings;
  onChange: (next: Partial<AdvancedTextElementSettings>) => void;
}) {
  return (
    <div data-assistant-group={title} className="rounded-2xl border border-slate-200 bg-white/85 p-4 dark:border-slate-700 dark:bg-slate-900/70">
      <div className="text-sm font-bold text-slate-900 dark:text-slate-100">{title}</div>
      <label className="mt-3 block">
        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Text</span>
        <AssistantInput data-assistant-permission="view"
          value={value.text ?? ""}
          onChange={(event) => onChange({ text: event.target.value })}
          placeholder={placeholder}
          className={inputClass}
        />
      </label>
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Color</span>
          <AssistantInput data-assistant-permission="view"
            type="color"
            value={value.color || "#111827"}
            onChange={(event) => onChange({ color: event.target.value })}
            className="mt-1 h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-900"
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Size</span>
          <NumberInput
            value={value.size ?? defaultSize}
            fallback={defaultSize}
            onValidChange={(next) => onChange({ size: next })}
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">X offset (px)</span>
          <NumberInput
            step="1"
            value={value.xOffset ?? DEFAULT_VALUES.offset}
            fallback={DEFAULT_VALUES.offset}
            onValidChange={(next) => onChange({ xOffset: next })}
          />
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">Y offset (px)</span>
          <NumberInput
            step="1"
            value={value.yOffset ?? DEFAULT_VALUES.offset}
            fallback={DEFAULT_VALUES.offset}
            onValidChange={(next) => onChange({ yOffset: next })}
          />
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-3">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <AssistantInput data-assistant-permission="view"
            type="checkbox"
            checked={Boolean(value.bold)}
            onChange={(event) => onChange({ bold: event.target.checked })}
            className="h-4 w-4 accent-sky-600"
          />
          Bold
        </label>
        <label className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <AssistantInput data-assistant-permission="view"
            type="checkbox"
            checked={Boolean(value.italic)}
            onChange={(event) => onChange({ italic: event.target.checked })}
            className="h-4 w-4 accent-sky-600"
          />
          Italic
        </label>
      </div>
    </div>
  );
}

function numberToDraft(value: number | undefined, fallback: number | undefined): string {
  const source = Number.isFinite(value) ? value : fallback;
  return Number.isFinite(source) ? String(source) : "";
}

function NumberInput({
  value,
  ariaLabel,
  fallback,
  onValidChange,
  className = inputClass,
  min,
  max,
  step,
}: {
  value: number | undefined;
  ariaLabel?: string;
  // The value the field shows when it holds nothing. `undefined` makes the
  // field clearable: emptying it means "inherit", which is what a per-condition
  // override needs and what a general setting must never do.
  fallback: number | undefined;
  onValidChange: (value: number | undefined) => void;
  className?: string;
  min?: string;
  // Opacities are bounded at both ends; nothing here needed an upper bound
  // before.
  max?: string;
  step?: string;
}) {
  const [draft, setDraft] = useState(() => numberToDraft(value, fallback));

  useEffect(() => {
    setDraft(numberToDraft(value, fallback));
  }, [fallback, value]);

  function commit(nextDraft: string) {
    setDraft(nextDraft);
    const trimmed = nextDraft.trim();
    if (!trimmed && fallback === undefined) {
      onValidChange(undefined);
      return;
    }
    if (!trimmed || trimmed === "-" || trimmed === "." || trimmed === ",") {
      return;
    }
    const next = numberOrUndefined(trimmed);
    if (next !== undefined) {
      onValidChange(next);
    }
  }

  return (
    <AssistantInput data-assistant-permission="view"
      type="number"
      aria-label={ariaLabel}
      min={min}
      max={max}
      step={step}
      value={draft}
      onChange={(event) => commit(event.target.value)}
      onBlur={() => {
        if (!draft.trim() && fallback !== undefined) {
          setDraft(numberToDraft(value, fallback));
        }
      }}
      className={className}
    />
  );
}

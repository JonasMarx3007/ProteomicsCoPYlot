import type { AdvancedPlotSettings } from "./types";

export function compactTextElement(value: AdvancedPlotSettings["titleElement"]) {
  if (!value) return undefined;
  const text = value.text?.trim();
  const next = {
    ...(text ? { text } : {}),
    ...(value.size && value.size > 0 ? { size: value.size } : {}),
    ...(value.xOffset ? { xOffset: value.xOffset } : {}),
    ...(value.yOffset ? { yOffset: value.yOffset } : {}),
    ...(value.bold ? { bold: true } : {}),
    ...(value.italic ? { italic: true } : {}),
    ...(value.color?.trim() ? { color: value.color.trim() } : {}),
  };
  return Object.keys(next).length ? next : undefined;
}

export function compactMap(value: Record<string, string> | undefined): Record<string, string> | undefined {
  const entries = Object.entries(value ?? {})
    .map(([key, val]) => [key.trim(), val.trim()] as const)
    .filter(([key, val]) => key && val);
  return entries.length ? Object.fromEntries(entries) : undefined;
}

// Every marker setting, in one place.
//
// The three compactors that feed the `advanced` query param are near-copies of
// each other, and each one that forgets a key drops it silently: the panel
// stores it, the URL never carries it, and the plot renders as though it had
// never been set. So the marker keys are listed once here and spliced into all
// three, rather than written out three times and kept in step by hand.
// The per-condition override maps. Compacted like the label and colour maps:
// empty entries dropped, everything else kept, including a zero.
const MARKER_NUMBER_MAP_KEYS = [
  "conditionMarkerSizes",
  "conditionMarkerAlphas",
  "conditionMarkerEdgeWidths",
] as const;

const MARKER_TEXT_MAP_KEYS = [
  "conditionMarkerShapes",
  "conditionMarkerEdgeColors",
] as const;

const MARKER_NUMBER_KEYS = [
  "valueLabelSize",
  "markerSize",
  "markerAlpha",
  "markerEdgeWidth",
  "boxPointSize",
  "boxPointAlpha",
  "boxPointEdgeWidth",
  "volcanoUpSize",
  "volcanoUpAlpha",
  "volcanoDownSize",
  "volcanoDownAlpha",
  "volcanoNsSize",
  "volcanoNsAlpha",
  "volcanoHighlightSize",
  "volcanoLabelSize",
] as const;

const ELEMENT_EXTRA_KEYS = [
  "legendTitle",
  "legendTextColor",
  "xTickLabelColor",
  "yTickLabelColor",
] as const;

const ELEMENT_BOOLEAN_KEYS = ["titleVisible", "legendVisible", "legendFrame"] as const;

const MARKER_TEXT_KEYS = ["markerShape"] as const;

const FONT_KEYS = [
  "fontFamily",
  "titleFontFamily",
  "axisLabelFontFamily",
  "tickFontFamily",
  "legendFontFamily",
  "valueLabelFontFamily",
] as const;

const MARKER_COLOR_KEYS = [
  "markerColor",
  "markerEdgeColor",
  "barColor",
  "classIColor",
  "classNotIColor",
  "vennColor1",
  "vennColor2",
  "vennColor3",
  "boxPointEdgeColor",
  "volcanoUpColor",
  "volcanoDownColor",
  "volcanoNsColor",
  "volcanoHighlightColor",
] as const;

export function compactMarkerSettings(
  settings: AdvancedPlotSettings
): Partial<AdvancedPlotSettings> {
  const next: Record<string, number | string> = {};
  for (const key of MARKER_NUMBER_KEYS) {
    const value = settings[key];
    // Zero is kept deliberately: it is the setting for a fully transparent
    // point and for an outline that should not be drawn. The older compactors
    // dropped anything falsy, which made "no outline" unexpressible.
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
      next[key] = value;
    }
  }
  for (const key of [...MARKER_COLOR_KEYS, ...MARKER_TEXT_KEYS]) {
    const value = settings[key]?.trim();
    if (value) next[key] = value;
  }
  const maps: Record<string, Record<string, number | string>> = {};
  for (const key of MARKER_NUMBER_MAP_KEYS) {
    const entries = Object.entries(settings[key] ?? {}).filter(
      ([group, entry]) => group.trim() && typeof entry === "number" && Number.isFinite(entry)
    );
    if (entries.length) maps[key] = Object.fromEntries(entries);
  }
  for (const key of MARKER_TEXT_MAP_KEYS) {
    const compacted = compactMap(settings[key]);
    if (compacted) maps[key] = compacted;
  }
  return { ...next, ...maps } as Partial<AdvancedPlotSettings>;
}

// The element settings that are neither markers nor part of the older
// hand-written lists. Same reason as the markers: one place, spliced into every
// compactor, so a new key cannot be forgotten by two of the three.
export function compactElementSettings(
  settings: AdvancedPlotSettings
): Partial<AdvancedPlotSettings> {
  const next: Record<string, string | boolean> = {};
  for (const key of ELEMENT_EXTRA_KEYS) {
    const value = settings[key]?.trim();
    if (value) next[key] = value;
  }
  for (const key of ELEMENT_BOOLEAN_KEYS) {
    const value = settings[key];
    // Kept even when false: "no legend" and "no frame" are instructions.
    if (typeof value === "boolean") next[key] = value;
  }
  return next as Partial<AdvancedPlotSettings>;
}

/**
 * The one compaction of an advanced-settings object into what the URL carries.
 *
 * There used to be three near-copies of this -- in `App.tsx`, the QC page and
 * the Completeness page -- and they had drifted. The Completeness page dropped
 * the legend, box, colour-scale, condition-label and condition-colour keys, and
 * `textXOffset`/`textYOffset` were forwarded only by the page whose plots do
 * not read them. Each omission is silent in exactly the same way: the panel
 * stores the setting, the URL never carries it, and the plot comes back looking
 * as though it had never been set.
 *
 * Anything dropped here is dropped because it is empty, never because it
 * matches some default. The panel stores only what the user changed, so every
 * stored value is an instruction: "solid" on a plot whose grid is natively
 * dashed is a change, and dropping it as "the default" used to swallow it.
 * Zero and `false` are values, not absences: a fully transparent point, an
 * outline that should not be drawn and a legend that should not appear are all
 * instructions.
 */
export function compactAdvancedPlotSettings(
  settings: AdvancedPlotSettings
): AdvancedPlotSettings {
  const next: AdvancedPlotSettings = {};
  const trimmed = (value: string | undefined) => value?.trim();

  const titleElement = compactTextElement(settings.titleElement);
  const xLabelElement = compactTextElement(settings.xLabelElement);
  const yLabelElement = compactTextElement(settings.yLabelElement);
  if (titleElement) next.titleElement = titleElement;
  if (xLabelElement) next.xLabelElement = xLabelElement;
  if (yLabelElement) next.yLabelElement = yLabelElement;

  const positive = (value: number | undefined) =>
    typeof value === "number" && Number.isFinite(value) && value > 0;
  if (positive(settings.xTickLabelSize)) next.xTickLabelSize = settings.xTickLabelSize;
  if (positive(settings.yTickLabelSize)) next.yTickLabelSize = settings.yTickLabelSize;
  if (Number.isFinite(settings.xTickLabelRotation)) {
    next.xTickLabelRotation = settings.xTickLabelRotation;
  }
  if (Number.isFinite(settings.yTickLabelRotation)) {
    next.yTickLabelRotation = settings.yTickLabelRotation;
  }
  if (settings.textXOffset) next.textXOffset = settings.textXOffset;
  if (settings.textYOffset) next.textYOffset = settings.textYOffset;

  if (positive(settings.legendFontSize)) next.legendFontSize = settings.legendFontSize;
  if (settings.legendXOffset) next.legendXOffset = settings.legendXOffset;
  if (settings.legendYOffset) next.legendYOffset = settings.legendYOffset;

  const referenceLineColor = trimmed(settings.referenceLineColor);
  const boxBorderColor = trimmed(settings.boxBorderColor);
  const boxMedianColor = trimmed(settings.boxMedianColor);
  const boxOutlierColor = trimmed(settings.boxOutlierColor);
  const boxOutlierEdgeColor = trimmed(settings.boxOutlierEdgeColor);
  const correlationColorMap = trimmed(settings.correlationColorMap);
  if (referenceLineColor) next.referenceLineColor = referenceLineColor;
  // Only `false` is worth sending: the line is drawn unless it is switched off,
  // so `true` is the backend's own default and costs a key for nothing.
  if (settings.referenceLineVisible === false) next.referenceLineVisible = false;
  const referenceLineStyle = trimmed(settings.referenceLineStyle);
  if (referenceLineStyle) next.referenceLineStyle = referenceLineStyle;
  if (positive(settings.referenceLineWidth)) {
    next.referenceLineWidth = settings.referenceLineWidth;
  }
  if (positive(settings.rowLabelSize)) next.rowLabelSize = settings.rowLabelSize;
  const rowLabelColor = trimmed(settings.rowLabelColor);
  if (rowLabelColor) next.rowLabelColor = rowLabelColor;

  // Fonts. Each is a name from PLOT_FONTS; an element left on "Same as all
  // text" sends nothing, which is what makes it follow the global one.
  for (const key of FONT_KEYS) {
    const font = trimmed(settings[key]);
    if (font) next[key] = font;
  }
  if (boxBorderColor) next.boxBorderColor = boxBorderColor;
  if (boxMedianColor) next.boxMedianColor = boxMedianColor;
  if (boxOutlierColor) next.boxOutlierColor = boxOutlierColor;
  if (boxOutlierEdgeColor) next.boxOutlierEdgeColor = boxOutlierEdgeColor;
  if (positive(settings.boxOutlierSize)) next.boxOutlierSize = settings.boxOutlierSize;
  if (correlationColorMap) next.correlationColorMap = correlationColorMap;

  const backgroundColor = trimmed(settings.backgroundColor);
  const plotTheme = trimmed(settings.plotTheme);
  if (backgroundColor) next.backgroundColor = backgroundColor;
  if (typeof settings.transparentBackground === "boolean") {
    next.transparentBackground = settings.transparentBackground;
  }
  if (plotTheme && plotTheme !== "default") next.plotTheme = plotTheme;

  const axisLineColor = trimmed(settings.axisLineColor);
  const axisLineStyle = trimmed(settings.axisLineStyle);
  if (typeof settings.axisLineVisible === "boolean") {
    next.axisLineVisible = settings.axisLineVisible;
  }
  if (axisLineColor) next.axisLineColor = axisLineColor;
  if (positive(settings.axisLineWidth)) next.axisLineWidth = settings.axisLineWidth;
  if (axisLineStyle) next.axisLineStyle = axisLineStyle;
  if (typeof settings.axisLineTop === "boolean") next.axisLineTop = settings.axisLineTop;
  if (typeof settings.axisLineRight === "boolean") next.axisLineRight = settings.axisLineRight;
  if (typeof settings.axisLineBottom === "boolean") next.axisLineBottom = settings.axisLineBottom;
  if (typeof settings.axisLineLeft === "boolean") next.axisLineLeft = settings.axisLineLeft;

  const gridLineAxis = trimmed(settings.gridLineAxis);
  const gridLineColor = trimmed(settings.gridLineColor);
  const gridLineStyle = trimmed(settings.gridLineStyle);
  if (typeof settings.gridLineVisible === "boolean") {
    next.gridLineVisible = settings.gridLineVisible;
  }
  if (gridLineAxis) next.gridLineAxis = gridLineAxis;
  if (gridLineColor) next.gridLineColor = gridLineColor;
  if (positive(settings.gridLineWidth)) next.gridLineWidth = settings.gridLineWidth;
  if (gridLineStyle) next.gridLineStyle = gridLineStyle;

  const conditionLabels = compactMap(settings.conditionLabels);
  const sampleLabels = compactMap(settings.sampleLabels);
  const conditionColors = compactMap(settings.conditionColors);
  if (conditionLabels) next.conditionLabels = conditionLabels;
  if (sampleLabels) next.sampleLabels = sampleLabels;
  if (conditionColors) next.conditionColors = conditionColors;

  Object.assign(next, compactMarkerSettings(settings), compactElementSettings(settings));
  return next;
}

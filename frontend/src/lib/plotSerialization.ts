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

function compactMarkerSettings(
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
function compactElementSettings(
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
 * the text offsets were forwarded only by the page whose plots did
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
  stored: AdvancedPlotSettings
): AdvancedPlotSettings {
  const settings = migrateAdvancedPlotSettings(stored);
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
  if (settings.referenceLineLegend === false) next.referenceLineLegend = false;
  // The highlight ring's legend entry is drawn unless switched off; its label
  // only matters when it differs from the default.
  if (settings.volcanoHighlightLegend === false) next.volcanoHighlightLegend = false;
  const highlightLegendLabel = trimmed(settings.volcanoHighlightLegendLabel);
  if (highlightLegendLabel) next.volcanoHighlightLegendLabel = highlightLegendLabel;
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

/**
 * Settings saved by an older panel, in the keys the current one writes.
 *
 * The single frame switch (`axisLineVisible`) became four per-side boxes, so an
 * old "frame off" is all four sides off unless a side was already set on its
 * own; the value-label offsets (`textXOffset`/`textYOffset`) had no control
 * since the redesign and are dropped. Applied where a saved session's settings
 * are read back, so the panel shows what the plot draws. The backend does the
 * same (`migrate_advanced_plot_settings` in plot_styling.py) for reports and
 * any request that still carries the old keys.
 */
export function migrateAdvancedPlotSettings(settings: AdvancedPlotSettings): AdvancedPlotSettings {
  const legacy = settings as AdvancedPlotSettings & {
    axisLineVisible?: unknown;
    textXOffset?: unknown;
    textYOffset?: unknown;
  };
  if (!("axisLineVisible" in legacy) && !("textXOffset" in legacy) && !("textYOffset" in legacy)) {
    return settings;
  }
  const { axisLineVisible, textXOffset: _x, textYOffset: _y, ...rest } = legacy;
  void _x;
  void _y;
  const next: AdvancedPlotSettings = { ...rest };
  if (typeof axisLineVisible === "boolean") {
    next.axisLineTop ??= axisLineVisible;
    next.axisLineRight ??= axisLineVisible;
    next.axisLineBottom ??= axisLineVisible;
    next.axisLineLeft ??= axisLineVisible;
  }
  return next;
}

/** `migrateAdvancedPlotSettings` over a saved map of plot keys or tabs. */
export function migrateAdvancedSettingsMap<K extends string>(
  settings: Partial<Record<K, AdvancedPlotSettings>>
): Partial<Record<K, AdvancedPlotSettings>> {
  const next: Partial<Record<K, AdvancedPlotSettings>> = {};
  for (const [key, value] of Object.entries(settings) as [K, AdvancedPlotSettings | undefined][]) {
    if (value && typeof value === "object") next[key] = migrateAdvancedPlotSettings(value);
  }
  return next;
}

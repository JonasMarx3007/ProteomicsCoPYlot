// The canvas's saved-state migrations and its tiles' appearance rules, kept out
// of AnalysisPage.tsx so they can be tested directly
// (tests/unit/shared-helpers.test.ts, tests/unit/plot-control-visibility.test.tsx).
import type { AdvancedPlotVisibleControls } from "../../components/plots/AdvancedPlotOptions";
import type { AdvancedPlotSettings, ListEnrichmentRequest, ListEnrichmentResultResponse } from "../../lib/types";

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/**
 * The canvas volcano is styled with the same settings as every other plot.
 *
 * It used to carry its own five-field shape -- title, point radius and the
 * three class colours -- edited in a panel of its own. Those are exactly the
 * Title and Volcano points cards of `AdvancedPlotOptions`, so a colour set on
 * this tile had no effect anywhere else and vice versa. The tile now stores
 * `AdvancedPlotSettings` and a saved canvas is migrated on read.
 */
export type VolcanoStyle = AdvancedPlotSettings;

export const CANVAS_VOLCANO_DEFAULTS = {
  up: "#dc2626",
  down: "#2563eb",
  other: "#94a3b8",
  radius: 2.8,
} as const;

export function restoredVolcanoStyle(value: unknown): VolcanoStyle {
  const saved = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  // Already the shared shape.
  if ("titleElement" in saved || "volcanoUpColor" in saved) {
    return saved as VolcanoStyle;
  }
  const color = (key: string, fallback: string) =>
    typeof saved[key] === "string" && /^#[0-9a-f]{6}$/i.test(saved[key] as string)
      ? (saved[key] as string)
      : fallback;
  const radius =
    typeof saved.radius === "number" && Number.isFinite(saved.radius)
      ? Math.min(10, Math.max(1, saved.radius))
      : CANVAS_VOLCANO_DEFAULTS.radius;
  const title = typeof saved.title === "string" ? saved.title : "";
  // The old radius was an SVG radius; the shared setting is a diameter.
  const size = radius * 2;
  return {
    ...(title ? { titleElement: { text: title } } : {}),
    volcanoUpColor: color("up", CANVAS_VOLCANO_DEFAULTS.up),
    volcanoDownColor: color("down", CANVAS_VOLCANO_DEFAULTS.down),
    volcanoNsColor: color("other", CANVAS_VOLCANO_DEFAULTS.other),
    volcanoUpSize: size,
    volcanoDownSize: size,
    volcanoNsSize: size,
  };
}

/** One class of point, as the SVG needs it. */
export function canvasPointStyle(style: VolcanoStyle, significance: string) {
  const lower = significance.toLowerCase();
  const [colorKey, sizeKey, alphaKey, fallbackColor] = lower.includes("up")
    ? (["volcanoUpColor", "volcanoUpSize", "volcanoUpAlpha", CANVAS_VOLCANO_DEFAULTS.up] as const)
    : lower.includes("down")
    ? (["volcanoDownColor", "volcanoDownSize", "volcanoDownAlpha", CANVAS_VOLCANO_DEFAULTS.down] as const)
    : (["volcanoNsColor", "volcanoNsSize", "volcanoNsAlpha", CANVAS_VOLCANO_DEFAULTS.other] as const);
  const size = style[sizeKey];
  const alpha = style[alphaKey];
  return {
    color: style[colorKey] || fallbackColor,
    // Diameter in the shared vocabulary, radius in SVG.
    radius: (typeof size === "number" && size > 0 ? size : CANVAS_VOLCANO_DEFAULTS.radius * 2) / 2,
    opacity: typeof alpha === "number" ? Math.min(1, Math.max(0, alpha)) : 1,
  };
}

export type CompletedOra = {
  result: ListEnrichmentResultResponse;
  request: ListEnrichmentRequest;
  inputSource: "manual" | "list";
  namedList: string;
};

export type OraState = {
  sourceMode: "manual" | "list";
  selectedListName: string;
  genesText: string;
  backgroundMode: "experiment" | "global";
  backgroundText: string;
  topN: number;
  minTermSize: number;
  maxTermSize: number;
  adjPValueCutoff: number;
  completed: CompletedOra | null;
};

export function restoredOraState(value: unknown): OraState {
  const saved = value && typeof value === "object" ? value as Record<string, unknown> : {};
  return {
    sourceMode: saved.sourceMode === "list" ? "list" : "manual",
    selectedListName: asString(saved.selectedListName), genesText: asString(saved.genesText),
    backgroundMode: saved.backgroundMode === "global" ? "global" : "experiment",
    backgroundText: asString(saved.backgroundText), topN: asNumber(saved.topN, 10),
    minTermSize: asNumber(saved.minTermSize, 20), maxTermSize: asNumber(saved.maxTermSize, 300),
    adjPValueCutoff: asNumber(saved.adjPValueCutoff, 0.05),
    completed: isCompletedOra(saved.completed) ? saved.completed : null,
  };
}

export function isCompletedOra(value: unknown): value is CompletedOra {
  const record = (item: unknown): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item));
  const strings = (item: unknown): item is string[] => Array.isArray(item) && item.every(value => typeof value === "string");
  const numbers = (item: Record<string, unknown>, keys: string[]) => keys.every(key => typeof item[key] === "number" && Number.isFinite(item[key]) && Number(item[key]) >= 0);
  if (!record(value) || !record(value.result) || !record(value.request)) return false;
  const result = value.result, request = value.request;
  return (value.inputSource === "manual" || value.inputSource === "list") && typeof value.namedList === "string" &&
    strings(request.genes) && strings(request.backgroundGenes) &&
    (request.backgroundMode === "experiment" || request.backgroundMode === "global") &&
    numbers(request, ["topN", "minTermSize", "maxTermSize", "adjPValueCutoff"]) &&
    strings(result.genes) && strings(result.backgroundGenes) && strings(result.warnings) &&
    (result.backgroundMode === "experiment" || result.backgroundMode === "global") &&
    ["organism", "correctionMethod", "databaseSha256"].every(key => typeof result[key] === "string") &&
    (result.evidenceToken === undefined || typeof result.evidenceToken === "string") &&
    numbers(result, ["backgroundSize", "annotatedBackgroundSize", "testedTermCount"]) &&
    record(result.termCounts) && record(result.termCounts.query) && Object.values(result.termCounts).every(counts =>
      record(counts) && numbers(counts, ["searchSpace", "overlapTested", "passingCutoff", "displayed"])) &&
    Array.isArray(result.terms) && result.terms.every(term => record(term) &&
      ["source", "termId", "name"].every(key => typeof term[key] === "string") &&
      numbers(term, ["termSize", "intersectionSize", "querySize", "geneRatio", "hitPercent", "pValue", "adjPValue"]) && strings(term.intersectingGenes));
}

/**
 * The appearance cards offered on the canvas volcano tile.
 *
 * This tile is drawn in the browser, so only the parts the SVG knows how to
 * honour are offered: no frame, grid, background theme or renderer-side maps.
 * The whole tile is typeset in the one face set on the <svg> element, and no
 * *FontFamily key is read anywhere in it, so there is no font to choose either.
 */
export const CANVAS_VOLCANO_VISIBLE_CONTROLS: AdvancedPlotVisibleControls = {
  volcanoMarkers: true,
  fontControls: false,
  legendControls: false,
  conditionLabels: false,
  sampleLabels: false,
  conditionColors: false,
  axisLineControls: false,
  backgroundControls: false,
};

/** The appearance cards offered on a canvas tile drawn by the backend. */
export function canvasImageVisibleControls(boxplot: boolean): AdvancedPlotVisibleControls {
  return { boxplotStyle: boxplot, boxplotOutliers: false, sampleLabels: false, referenceLineColor: false, correlationGradient: false };
}

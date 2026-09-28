import type { ContextMode } from "./types";

/**
 * Every view that reports a context mode, named `section` or `section:tab`.
 *
 * A view is where one set of selections determines what is on screen. Several
 * tabs can share one (the single-protein plots read the same selections); one
 * page can hold several (each QC plot reports its own).
 */
export const CONTEXT_SLOTS = [
  "qc:boxplot", "qc:pca", "qc:abundance", "qc:coverage",
  "completeness",
  "stats:volcano", "stats:anova", "stats:ora", "stats:pathwayHeatmap", "stats:simulation",
  "peptide", "singleProtein", "comparison", "phospho", "phospho:ksea",
  "data:distribution", "analysis",
] as const;

export type ContextSlot = (typeof CONTEXT_SLOTS)[number];
export type ContextModes = Partial<Record<ContextSlot, ContextMode>>;

export type Navigation = {
  section: string;
  dataTab: string;
  qcTab: string;
  statsTab: string;
  completenessTab: string;
  peptideTab: string;
  singleProteinTab: string;
  comparisonTab: string;
  phosphoTab: string;
};

const QC_SLOTS: Record<string, ContextSlot> = {
  boxplot: "qc:boxplot", pca: "qc:pca", abundance: "qc:abundance", coverage: "qc:coverage",
};
const STATS_SLOTS: Record<string, ContextSlot> = {
  volcano: "stats:volcano", anova: "stats:anova", ora: "stats:ora",
  pathwayHeatmap: "stats:pathwayHeatmap", simulation: "stats:simulation",
};
const TABS_WITH_A_MODE: Record<string, string[]> = {
  completeness: ["missingPlot", "heatmap", "tables"],
  peptide: ["rtPlot", "modification", "missedCleavage", "sequenceCoverage"],
  singleProtein: ["boxplot", "lineplot", "heatmap"],
  comparison: ["pearson", "venn"],
  phospho: ["phosphositePlot", "coverage", "distribution", "sty", "phosprotRegulation"],
};

/** The view on screen, when it is one that reports a context mode. */
export function activeContextSlot(nav: Navigation): ContextSlot | null {
  switch (nav.section) {
    case "analysis":
      return "analysis";
    case "data":
      return nav.dataTab === "distribution" ? "data:distribution" : null;
    case "qc":
      return QC_SLOTS[nav.qcTab] ?? null;
    case "stats":
      return STATS_SLOTS[nav.statsTab] ?? null;
    case "completeness":
      return TABS_WITH_A_MODE.completeness.includes(nav.completenessTab) ? "completeness" : null;
    case "peptide":
      return TABS_WITH_A_MODE.peptide.includes(nav.peptideTab) ? "peptide" : null;
    case "singleProtein":
      return TABS_WITH_A_MODE.singleProtein.includes(nav.singleProteinTab) ? "singleProtein" : null;
    case "comparison":
      return TABS_WITH_A_MODE.comparison.includes(nav.comparisonTab) ? "comparison" : null;
    case "phospho":
      if (nav.phosphoTab === "ksea") return "phospho:ksea";
      return TABS_WITH_A_MODE.phospho.includes(nav.phosphoTab) ? "phospho" : null;
    default:
      return null;
  }
}

/**
 * The store after `slot` reports `mode`; null withdraws the view's entry.
 *
 * A page re-reports on every render of its effect, with a new object each time.
 * Returning the same store when nothing changed keeps that from re-rendering
 * the whole app.
 */
export function withContextMode(modes: ContextModes, slot: ContextSlot, mode: ContextMode | null): ContextModes {
  const current = modes[slot];
  if (mode === null) {
    if (current === undefined) return modes;
    const next = { ...modes };
    delete next[slot];
    return next;
  }
  if (current !== undefined && JSON.stringify(current) === JSON.stringify(mode)) return modes;
  return { ...modes, [slot]: mode };
}

/** Only the view on screen keeps its selections. */
export function keepOnly(modes: ContextModes, slot: ContextSlot | null): ContextModes {
  const kept = slot ? modes[slot] : undefined;
  const others = Object.keys(modes).some((key) => key !== slot);
  if (!others) return modes;
  return kept === undefined || slot === null ? {} : { [slot]: kept };
}

/** A text value from a context mode, lower-cased for comparison; "" when absent. */
export function contextText(mode: ContextMode | null | undefined, key: string): string {
  const value = mode?.[key];
  return typeof value === "string" ? value.toLowerCase() : "";
}

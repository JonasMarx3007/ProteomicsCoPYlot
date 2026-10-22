// Plain helpers the statistics panels share: option lists, warning filters and
// the restore rules for values read back from a saved session.

import type { AnovaClusterMethod, StatsTestType, StatisticalOptionsResponse } from "../../lib/types";
import { PAIRED_TEST_TYPES } from "../../lib/statisticalTests";

export function isPairedTestType(value: StatsTestType): boolean {
  return PAIRED_TEST_TYPES.includes(value);
}

export function conditionOptions(options: StatisticalOptionsResponse | null) {
  return (options?.availableConditions ?? []).map((item) => ({ value: item, label: item }));
}

export function hasGeneNameSupport(options: StatisticalOptionsResponse | null) {
  return (options?.availableIdentifiers ?? []).some((item) => item.key === "genes");
}

export function removeSourceUsageWarnings(warnings: string[] | undefined): string[] {
  if (!warnings || warnings.length === 0) return [];
  return warnings.filter((warning) => {
    const normalized = warning.trim().toLowerCase();
    if (!normalized) return false;
    if (normalized.includes("using raw data because filtered/log2 annotated data is unavailable")) {
      return false;
    }
    if (normalized.includes("using imputed data for statistical analysis")) {
      return false;
    }
    if (normalized.includes("imputation settings were detected")) {
      return false;
    }
    return true;
  });
}

// Condition names come from user-supplied annotation files, so they can contain
// characters a filesystem will not accept. Keep letters, digits, dot, dash and
// underscore; collapse everything else to a single underscore.
export function sanitizeFilenamePart(value: string): string {
  const cleaned = value.trim().replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned.slice(0, 40);
}

// A saved state written by an older build can hold a value of the wrong shape.
// `Number("n/a")` is NaN, and NaN survives Math.round, so it reaches the request
// and the backend rejects the run with a 422. Fall back, and clamp to the range
// the schema accepts so a restored value cannot be refused either.
function restoreNumber(
  value: unknown,
  fallback: number,
  { min, max }: { min: number; max: number }
): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function restoreClusterCount(value: unknown): number {
  // Matches AnovaRequest.nClusters: ge=1, le=100.
  return Math.round(restoreNumber(value, 4, { min: 1, max: 100 }));
}

export function restorePValueThreshold(value: unknown): number {
  // Matches the schema's gt=0.0, le=1.0.
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0 || parsed > 1) return 0.05;
  return parsed;
}

// Hierarchical linkage offered for ANOVA row clustering. Mirrors
// AnovaClusterMethod in backend/app/schemas/stats.py; the metric is fixed at
// euclidean backend-side, so every method here is always a valid pair.
//
// Average is the default and what the clustering has always used, but it chains:
// on a typical run k=4 can return two large clusters and two of a handful of
// features. Ward is the usual remedy.
export const ANOVA_CLUSTER_METHOD_OPTIONS: { value: AnovaClusterMethod; label: string }[] = [
  { value: "average", label: "Average (UPGMA)" },
  { value: "ward", label: "Ward" },
  { value: "complete", label: "Complete" },
  { value: "weighted", label: "Weighted (WPGMA)" },
  { value: "single", label: "Single" },
];

const ANOVA_CLUSTER_METHOD_VALUES: string[] = ANOVA_CLUSTER_METHOD_OPTIONS.map(
  (option) => option.value
);

export function restoreClusterMethod(value: unknown): AnovaClusterMethod {
  const text = String(value ?? "").trim();
  return ANOVA_CLUSTER_METHOD_VALUES.includes(text)
    ? (text as AnovaClusterMethod)
    : "average";
}

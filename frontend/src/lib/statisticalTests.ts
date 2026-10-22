import { useEffect, useState } from "react";
import { getStatisticsCapability } from "./api";
import type { StatsTestType } from "./types";

// Keep wire values aligned with backend StatsTestType. Paired tests operate
// on within-pair differences; they are not pooled independent-sample tests.
// The moderated tests run in R limma, so a page offers them only when the
// installation can run them (useTestTypeOptions below), as VSN is offered.
export const TEST_TYPE_OPTIONS: { value: StatsTestType; label: string }[] = [
  { value: "unpaired", label: "Unpaired (Student's t, equal variance)" },
  { value: "unpaired_welch", label: "Unpaired (Welch, unequal variance)" },
  { value: "paired", label: "Paired t-test (matched samples)" },
  { value: "moderated", label: "Unpaired moderated t (limma)" },
  { value: "moderated_robust", label: "Unpaired moderated t (limma, robust)" },
  { value: "moderated_paired", label: "Paired moderated t (limma)" },
  { value: "moderated_robust_paired", label: "Paired moderated t (limma, robust)" },
];
export const TEST_TYPE_VALUES = TEST_TYPE_OPTIONS.map((option) => option.value);
export const MODERATED_TEST_TYPES: StatsTestType[] = ["moderated", "moderated_robust", "moderated_paired", "moderated_robust_paired"];
export const PAIRED_TEST_TYPES: StatsTestType[] = ["paired", "moderated_paired", "moderated_robust_paired"];
export function isModeratedTestType(value: string): boolean {
  return (MODERATED_TEST_TYPES as string[]).includes(value);
}
export const CONTROL_TEST_TYPE_OPTIONS = [
  { value: "unpaired_welch", label: "Unpaired (propagated variance)" },
  { value: "paired", label: "Paired (propagated control variance)" },
];
/** Control-corrected volcanoes propagate four variances; limma does not, so they fall back. */
export function controlTestType(value: StatsTestType): StatsTestType {
  if (value === "unpaired" || value === "moderated" || value === "moderated_robust") return "unpaired_welch";
  if (value === "moderated_paired" || value === "moderated_robust_paired") return "paired";
  return value;
}
export const TEST_TYPE_LABELS = Object.fromEntries(TEST_TYPE_OPTIONS.map(({ value, label }) => [value, label]));
export const SIMULATION_TEST_TYPE_OPTIONS = TEST_TYPE_OPTIONS.filter(
  ({ value }) => !PAIRED_TEST_TYPES.includes(value) && !isModeratedTestType(value)
);

export function restoreTestType(value: unknown): StatsTestType {
  const text = String(value ?? "unpaired").trim();
  return TEST_TYPE_VALUES.includes(text as StatsTestType) ? text as StatsTestType : "unpaired";
}

/** The test types this installation offers: all of them, minus the moderated ones without R + limma. */
export function testTypeOptions(moderatedAvailable: boolean): { value: StatsTestType; label: string }[] {
  return moderatedAvailable ? TEST_TYPE_OPTIONS : TEST_TYPE_OPTIONS.filter(({ value }) => !isModeratedTestType(value));
}

let cachedModerated: boolean | null = null;
let pending: Promise<boolean> | null = null;
function fetchModeratedAvailable(): Promise<boolean> {
  if (cachedModerated !== null) return Promise.resolve(cachedModerated);
  if (!pending) {
    pending = getStatisticsCapability()
      .then((payload) => (cachedModerated = payload.moderatedAvailable))
      .catch(() => false)
      .finally(() => { pending = null; });
  }
  return pending;
}

/**
 * The test-type select options for this installation, with a stored choice
 * that this installation cannot run mapped back to the default.
 */
export function useTestTypeOptions(): { options: { value: StatsTestType; label: string }[]; moderatedAvailable: boolean } {
  const [moderatedAvailable, setModeratedAvailable] = useState<boolean>(cachedModerated ?? false);
  useEffect(() => {
    let cancelled = false;
    fetchModeratedAvailable().then((ok) => { if (!cancelled) setModeratedAvailable(ok); });
    return () => { cancelled = true; };
  }, []);
  return { options: testTypeOptions(moderatedAvailable), moderatedAvailable };
}

/** A stored test type the installation cannot run falls back to the default rather than an empty select. */
export function availableTestType(value: StatsTestType, moderatedAvailable: boolean): StatsTestType {
  return !moderatedAvailable && isModeratedTestType(value) ? "unpaired" : value;
}

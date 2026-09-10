import type { StatsTestType } from "./types";

// Keep wire values aligned with backend StatsTestType. Paired tests operate
// on within-pair differences; they are not pooled independent-sample tests.
export const TEST_TYPE_OPTIONS: { value: StatsTestType; label: string }[] = [
  { value: "unpaired", label: "Unpaired (Student's t, equal variance)" },
  { value: "unpaired_welch", label: "Unpaired (Welch, unequal variance)" },
  { value: "paired", label: "Paired t-test (matched samples)" },
];
export const TEST_TYPE_VALUES = TEST_TYPE_OPTIONS.map((option) => option.value);
export const TEST_TYPE_LABELS = Object.fromEntries(TEST_TYPE_OPTIONS.map(({ value, label }) => [value, label]));
export const SIMULATION_TEST_TYPE_OPTIONS = TEST_TYPE_OPTIONS.filter(({ value }) => value !== "paired");

export function restoreTestType(value: unknown): StatsTestType {
  const text = String(value ?? "unpaired").trim();
  return TEST_TYPE_VALUES.includes(text as StatsTestType) ? text as StatsTestType : "unpaired";
}

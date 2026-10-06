/**
 * Every view that shows a plot or a result is one the assistant can explain.
 *
 * The assistant's evidence is keyed by view (`qc.cv`, `stats.volcano`, ...).
 * A tab added to the app without evidence behind it is a view the assistant
 * would answer about from nothing. Both sides are compared with
 * tests/fixtures/assistant_plot_modules.json: this file holds the app's tabs to
 * it, and tests/unit/assistant/test_ai_chat_context.py holds the backend's
 * evidence functions to it.
 *
 * This replaced a Python regular expression over the tab arrays in App.tsx;
 * the arrays live in src/lib/navigationTabs.ts now and are imported here.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import {
  comparisonTabs, completenessTabs, peptideTabs, phosphoTabs, qcTabs, singleProteinTabs, statsTabs,
} from "../../src/lib/navigationTabs";

const FIXTURE: string[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../../tests/fixtures/assistant_plot_modules.json"), "utf-8")
);

it("lists exactly the app's plot and result views", () => {
  const sections = {
    qc: qcTabs, completeness: completenessTabs, stats: statsTabs, peptide: peptideTabs,
    singleProtein: singleProteinTabs, phospho: phosphoTabs, comparison: comparisonTabs,
  };
  const modules = new Set(["data.distribution", "analysis.canvas"]);
  for (const [section, tabs] of Object.entries(sections)) {
    for (const tab of tabs) modules.add(`${section}.${tab.key}`);
  }
  expect([...modules].sort()).toEqual([...FIXTURE].sort());
});

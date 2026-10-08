// @vitest-environment node
import { describe, expect, it } from "vitest";

import { MANUAL_CHAPTERS } from "../../src/lib/manualChapters";
import {
  comparisonTabs, completenessTabs, dataTabs, externalTabs, peptideTabs,
  phosphoTabs, qcTabs, singleProteinTabs, statsTabs, summaryTabs,
} from "../../src/lib/navigationTabs";

describe("manual chapters", () => {
  it("give every page with a tab bar its chapter", () => {
    const sections = {
      data: dataTabs, qc: qcTabs, completeness: completenessTabs, stats: statsTabs,
      peptide: peptideTabs, singleProtein: singleProteinTabs, phospho: phosphoTabs,
      comparison: comparisonTabs, summary: summaryTabs, external: externalTabs,
    };
    const expected = Object.entries(sections).flatMap(([section, tabs]) => tabs.map((tab) => `${section}.${tab.key}`));
    expect(Object.keys(MANUAL_CHAPTERS).sort()).toEqual(expected.sort());
  });
});

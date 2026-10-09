/**
 * The advanced plot panel's point controls and its per-plot rules.
 *
 * A general point setting must clear the per-condition overrides it governs,
 * or every condition keeps its own value and the control appears to do
 * nothing. These drive the panel itself instead of reading its source.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AdvancedPlotOptions from "../../src/components/plots/AdvancedPlotOptions";
import type { AdvancedPlotSettings } from "../../src/lib/types";
import { advancedPlotKey, advancedVisibleControls } from "../../src/lib/advancedPanelRules";

const OVERRIDES: AdvancedPlotSettings = {
  conditionMarkerSizes: { A: 9 },
  conditionMarkerShapes: { A: "star" },
  conditionMarkerAlphas: { A: 0.2 },
  conditionMarkerEdgeWidths: { A: 3 },
  conditionMarkerEdgeColors: { A: "#ff0000" },
  volcanoUpSize: 7,
  volcanoDownSize: 7,
  volcanoNsSize: 7,
  volcanoUpAlpha: 0.1,
  volcanoDownAlpha: 0.1,
  volcanoNsAlpha: 0.1,
};

function panel(visible: Record<string, boolean>) {
  const onChange = vi.fn();
  render(
    <AdvancedPlotOptions value={OVERRIDES} onChange={onChange} conditionOptions={["A", "B"]}
      visibleControls={{ markerStyle: true, ...visible }} />
  );
  return onChange;
}

function field(label: string) {
  return screen.getAllByText(label)[0].closest("label")!.querySelector("input, select") as HTMLInputElement;
}

function setValue(element: HTMLInputElement, value: string) {
  fireEvent.change(element, { target: { value } });
  fireEvent.blur(element);
}

describe("a general point setting", () => {
  it.each([
    ["Dot size (pt)", "4", "markerSize", "conditionMarkerSizes"],
    ["Dot opacity (0-1)", "0.5", "markerAlpha", "conditionMarkerAlphas"],
    ["Dot outline width (0 = none)", "1", "markerEdgeWidth", "conditionMarkerEdgeWidths"],
    ["Dot outline color", "#00ff00", "markerEdgeColor", "conditionMarkerEdgeColors"],
    ["Dot shape", "square", "markerShape", "conditionMarkerShapes"],
  ])("%s clears the per-condition overrides of that setting", (label, value, key, map) => {
    const onChange = panel({});
    setValue(field(label), value);
    const next = onChange.mock.calls.at(-1)![0];
    expect(String(next[key])).toBe(value);
    expect(next[map]).toEqual({});
  });

  it("dot color is set without disturbing the overrides", () => {
    const onChange = panel({});
    setValue(field("Dot color"), "#123456");
    expect(onChange.mock.calls.at(-1)![0]).toMatchObject({ markerColor: "#123456", conditionMarkerSizes: { A: 9 } });
  });

  it("on a volcano, size and opacity also clear the three class overrides", () => {
    const onChange = panel({ volcanoMarkers: true });
    setValue(field("Dot size (pt)"), "4");
    let next = onChange.mock.calls.at(-1)![0];
    expect([next.volcanoUpSize, next.volcanoDownSize, next.volcanoNsSize]).toEqual([undefined, undefined, undefined]);
    setValue(field("Dot opacity (0-1)"), "0.5");
    next = onChange.mock.calls.at(-1)![0];
    expect([next.volcanoUpAlpha, next.volcanoDownAlpha, next.volcanoNsAlpha]).toEqual([undefined, undefined, undefined]);
  });
});

describe("which plots get the panel and which cards", () => {
  const nav = {
    activeSection: "peptide", activeDataTab: "upload", activeStatsTab: "volcano", activePeptideTab: "sequenceCoverage",
    activeSingleProteinTab: "boxplot", activePhosphoTab: "phosphositePlot", activeComparisonTab: "pearson",
  };

  it("offers no panel for sequence coverage, which draws an HTML map rather than a figure", () => {
    expect(advancedPlotKey(nav)).toBe(null);
    expect(advancedPlotKey({ ...nav, activePeptideTab: "rtPlot" })).toBe("peptide:rtPlot");
  });

  it.each(["comparison:venn", "comparison:pearson", "stats:ora", "phospho:distribution"])(
    "%s draws no legend, so it gets no legend card", (key) => {
      expect(advancedVisibleControls(key, {}).legendControls).toBe(false);
    });
});

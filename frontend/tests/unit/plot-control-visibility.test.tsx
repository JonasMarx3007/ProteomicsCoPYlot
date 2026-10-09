/**
 * The appearance panel shows a card only where the renderer reads it.
 *
 * A card on a plot that ignores it is a control that silently changes nothing.
 * Which cards a plot gets was checked against the renderers in
 * backend/app/services; these hold the answers for the plots whose renderers
 * were read, so a card that comes back on a plot that still ignores it fails.
 *
 * App's rules are a function (lib/advancedPanelRules.ts) and are asked
 * directly; the QC and Completeness pages are mounted and their panels read;
 * the canvas tiles' sets are in features/analysis/canvasState.ts. This replaced
 * a node --test file that cut each page's `useMemo` body out of its source and
 * compiled it. That the canvas volcano reads no font key is an ESLint rule
 * (eslint.config.js, CANVAS_RULES).
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdvancedPlotOptions from "../../src/components/plots/AdvancedPlotOptions";
import { CANVAS_VOLCANO_VISIBLE_CONTROLS, canvasImageVisibleControls } from "../../src/features/analysis/canvasState";
import CompletenessPage from "../../src/features/completeness/CompletenessPage";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import { advancedVisibleControls } from "../../src/lib/advancedPanelRules";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

describe("the shared panel", () => {
  it("keeps the dot color behind its own flag inside the Points card", () => {
    const { rerender } = render(<AdvancedPlotOptions value={{}} onChange={() => {}} visibleControls={{ markerStyle: true }} />);
    expect(screen.getAllByText("Dot size (pt)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Dot color").length).toBeGreaterThan(0);
    rerender(<AdvancedPlotOptions value={{}} onChange={() => {}} visibleControls={{ markerStyle: true, markerColor: false }} />);
    expect(screen.getAllByText("Dot size (pt)").length).toBeGreaterThan(0);
    expect(screen.queryByText("Dot color")).toBeNull();
    // Without the Points card there is no dot colour to offer.
    rerender(<AdvancedPlotOptions value={{}} onChange={() => {}} visibleControls={{}} />);
    expect(screen.queryByText("Dot color")).toBeNull();
  });
});

describe("App", () => {
  const at = (key: string, modes = {}) => advancedVisibleControls(key, modes);

  it("offers no value labels on plots that print no number", () => {
    // phospho_coverage_png prints no number on any bar, in either mode; its
    // class colours are read, so that card stays.
    expect(at("phospho:coverage").valueLabels).not.toBe(true);
    expect(at("phospho:coverage").phosphoClassColors).toBe(true);
    // peptide_modification_plot draws grouped bars and no text; the missed
    // cleavage plot beside it does write on its bars, and keeps the card.
    expect(at("peptide:modification").valueLabels).not.toBe(true);
    expect(at("peptide:missedCleavage").valueLabels).toBe(true);
  });

  it("offers a bar color only to the bar plots that read it", () => {
    // phospho_sty_png gives S, T and Y a fixed colour each.
    expect(at("phospho:sty").barColor).not.toBe(true);
    expect(at("phospho:phosphositePlot").barColor).toBe(true);
    expect(at("phospho:distribution").barColor).toBe(true);
  });

  it("offers threshold lines and dot colors where the renderer draws them", () => {
    // Neither phosphoprotein regulation renderer draws a threshold line, and
    // both colour their points through a colour scale.
    expect(at("phospho:phosprotRegulation").referenceLineColor).not.toBe(true);
    expect(at("phospho:phosprotRegulation").markerStyle).toBe(true);
    expect(at("phospho:phosprotRegulation").markerColor).toBe(false);
    // KSEA, which used to share that case, draws both threshold lines.
    expect(at("phospho:ksea").referenceLineColor).toBe(true);
    expect(at("phospho:ksea").markerColor).toBe(false);
    // Both Pearson renderers draw the fit line (the PNG since 2026-09-25), and
    // draw their points without a plot-chosen colour.
    const pearson = (type: string) => ({ comparison: { kind: "protein", type } });
    expect(at("comparison:pearson", pearson("Normal")).referenceLineColor).toBe(true);
    expect(at("comparison:pearson", pearson("Interactive")).referenceLineColor).toBe(true);
    expect(at("comparison:pearson", pearson("Interactive")).markerStyle).toBe(true);
    expect(at("comparison:pearson", pearson("Interactive")).markerColor).not.toBe(false);
    // The two scatter plots whose dot colour does reach their points.
    expect(at("data:distribution").markerColor).not.toBe(false);
    expect(at("peptide:rtPlot").markerColor).not.toBe(false);
  });

  it("follows the cluster heatmap's feature-name switch with the Row labels card", () => {
    expect(at("stats:anova", { "stats:anova": { showRowLabels: true } }).rowLabels).toBe(true);
    expect(at("stats:anova", { "stats:anova": { showRowLabels: false } }).rowLabels).toBe(false);
    expect(at("stats:anova").rowLabels).toBe(false);
  });

  it("offers the single-protein line plot no marker or condition-label card", () => {
    // single_protein_lineplot_plot draws a fixed circle marker and labels its x
    // axis from the annotation; the boxplot on the same page reads both.
    expect(at("singleProtein:lineplot").markerStyle).not.toBe(true);
    expect(at("singleProtein:lineplot").conditionLabels).toBe(false);
    expect(at("singleProtein:boxplot").boxplotPoints).toBe(true);
    expect(at("singleProtein:boxplot").conditionLabels).not.toBe(false);
  });
});

const QC_OPTIONS = {
  conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
  availableDataSources: ["data"], defaultDataSource: "data", centredPhosprotValues: false,
} as Awaited<ReturnType<typeof api.getQcPlotOptions>>;

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getQcPlotOptions).mockResolvedValue(QC_OPTIONS);
});

/** The cards the mounted page's panel offers, by the field labels inside them. */
async function offered() {
  await screen.findByText("Advanced Plot Options", {}, { timeout: 5000 });
  const has = (label: string) => screen.queryAllByText(label).length > 0;
  return { points: has("Dot size (pt)"), dotColor: has("Dot color"), barColor: has("Bar color"), valueLabels: has("Value labels") };
}

describe("the QC page", () => {
  function mount(activeTab: "coverage" | "pca" | "abundance", saved: Record<string, unknown> = {}) {
    sessionStorage.setItem("pcopylot.ui.qc.pipeline.v1", JSON.stringify(saved));
    render(<QCPipelinePage activeTab={activeTab} />);
  }

  it("hides the dot color on the PCA, where the condition palette decides it", async () => {
    mount("pca");
    expect(await offered()).toMatchObject({ points: true, dotColor: false });
  });

  it("hides it on a clustered PCA too", async () => {
    mount("pca", { pca: { colorBy: "Cluster", clusterMethod: "KMeans" } });
    expect(await offered()).toMatchObject({ points: true, dotColor: false });
  });

  it("hides the dot colour on the abundance plot, whose curves take their condition's colour", async () => {
    mount("abundance");
    expect(await offered()).toMatchObject({ points: true, dotColor: false });
  });

  it("keeps the dot color for the jittered dots over the coverage summary bars", async () => {
    mount("coverage", { coverage: { summary: true } });
    expect(await offered()).toMatchObject({ points: true, dotColor: true });
  });
});

describe("the Completeness page", () => {
  it("offers the missing-value plot the bar color and label size it reads", async () => {
    render(<CompletenessPage activeTab="missingPlot" />);
    expect(await offered()).toMatchObject({ barColor: true, valueLabels: true });
  });

  it("offers neither on the heatmap beside it", async () => {
    render(<CompletenessPage activeTab="heatmap" />);
    expect(await offered()).toMatchObject({ barColor: false, valueLabels: false });
  });
});

describe("the canvas", () => {
  it("offers the browser-drawn volcano tile no font it cannot apply", () => {
    expect(CANVAS_VOLCANO_VISIBLE_CONTROLS.volcanoMarkers).toBe(true);
    expect(CANVAS_VOLCANO_VISIBLE_CONTROLS.fontControls).toBe(false);
  });

  it("keeps the font card on the server-rendered canvas plots, which matplotlib draws", () => {
    expect(canvasImageVisibleControls(false).fontControls).not.toBe(false);
    expect(canvasImageVisibleControls(true).fontControls).not.toBe(false);
    expect(canvasImageVisibleControls(true).boxplotStyle).toBe(true);
  });
});

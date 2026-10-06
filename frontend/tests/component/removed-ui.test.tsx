/**
 * Explanatory boxes and provenance fields that were removed on purpose.
 *
 * Every one of these was on screen because somebody thought the user needed
 * telling, and each was taken out after being looked at: it either said what
 * the control already says, or recorded a fact (a database hash, a
 * correction-scope paragraph) that belongs in a report rather than beside a
 * figure. A removal has no code behind it, so nothing else stops it drifting
 * back; this file names what went and checks the rendered page, so putting one
 * back is a decision rather than an accident.
 *
 * This replaced checks that searched the source files for the removed strings.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AdvancedPlotOptions, {
  type AdvancedPlotVisibleControls,
} from "../../src/components/plots/AdvancedPlotOptions";
import RestorePage from "../../src/features/data/RestorePage";
import PhosphoSpecificPage from "../../src/features/phospho/PhosphoSpecificPage";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { oraExportRows, oraListExportRows } from "../../src/features/stats/oraExport";
import { SimulationPanel } from "../../src/features/stats/SimulationPanel";
import * as api from "../../src/lib/api";
import type { EnrichmentResultResponse, ListEnrichmentResultResponse, StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "./apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const PROTEIN = [{ value: "protein", label: "Protein" }];
const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] }, pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }],
  warnings: [], availableDataSources: ["data"], defaultDataSource: "data",
};
const TERM = {
  source: "BP", termId: "GO:1", name: "a process", termSize: 10, intersectionSize: 2, querySize: 5,
  geneRatio: 0.4, hitPercent: 20, pValue: 0.001, adjPValue: 0.01, intersectingGenes: ["G1", "G2"],
};
const COUNTS = { searchSpace: 100, overlapTested: 20, passingCutoff: 1, displayed: 1 };
// The fields that were dropped from the screen and the exports still arrive
// from the backend, so the checks below see them offered and not shown.
const RESULT = {
  kind: "protein", sourceUsed: "data", selectedCluster: null, clusterGenes: [], clusterTerms: [],
  upGenes: ["G1", "G2"], downGenes: [], upTerms: [TERM], downTerms: [], backgroundMode: "experiment",
  backgroundGenes: ["G1", "G2", "G3"], backgroundSize: 3, annotatedBackgroundSize: 3,
  organism: "hsapiens", correctionMethod: "fdr_bh", upstreamCorrectionMethod: "fdr_bh",
  databaseSha256: "f".repeat(64), correctionScope: "Correction scope paragraph",
  testedTermCount: 20, termCounts: { up: COUNTS, down: COUNTS, cluster: COUNTS }, warnings: [],
} as unknown as EnrichmentResultResponse;

const GONE_FROM_EXPORTS = ["databaseSha256", "correctionScope"];

function pageText() {
  return document.body.textContent ?? "";
}

describe("removed on purpose", () => {
  it("the restore page has no standing explanations in front of its buttons", () => {
    silenceNetwork();
    const save = async () => true;
    render(
      <RestorePage onApplyUiState={() => {}} onQuickSave={save} onQuickSaveAs={save}
        onPortableSave={save} onOpenStateFile={null} currentSaveFileName={null} />
    );
    expect(pageText()).not.toContain("Leaving or refreshing starts a new analysis");
    expect(pageText()).not.toContain("Save states are compatibility snapshots");
  });

  it("an ORA result has no provenance card; its organism sits in the summary row", async () => {
    silenceNetwork();
    serveDatasets(api);
    vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
    vi.mocked(api.runEnrichmentAnalysis).mockResolvedValue(RESULT);
    // A contrast to run: both conditions otherwise open on the first one.
    sessionStorage.setItem("pcopylot.ui.stats.ora.v1", JSON.stringify({ condition1: "A", condition2: "B" }));
    render(<OraPanel kindOptions={PROTEIN} />);
    await waitFor(() => expect(api.runEnrichmentAnalysis).toHaveBeenCalled(), { timeout: 3000 });
    await waitFor(() => expect(screen.getAllByText("hsapiens").length).toBeGreaterThan(0));
    for (const gone of ["ORA Provenance", "GO database SHA-256", "f".repeat(64), "Correction scope paragraph"]) {
      expect(pageText()).not.toContain(gone);
    }
    expect(screen.getAllByText("Organism").length).toBeGreaterThan(0);
  });

  it("the ORA downloads carry neither the database hash nor the correction scope", () => {
    const rows = oraExportRows(RESULT.upTerms, RESULT, { direction: "up" });
    const listRows = oraListExportRows(
      {
        request: { genes: ["G1"], backgroundMode: "experiment", backgroundGenes: [], topN: 10, minTermSize: 5,
          maxTermSize: 500, adjPValueCutoff: 0.05, organism: "hsapiens" },
        inputSource: "manual", namedList: "",
      },
      { ...RESULT, genes: ["G1"], terms: [TERM], termCounts: { query: COUNTS } } as unknown as ListEnrichmentResultResponse
    );
    for (const row of [...rows, ...listRows]) {
      for (const gone of GONE_FROM_EXPORTS) expect(row).not.toHaveProperty(gone);
      expect(row).toHaveProperty("organism", "hsapiens");
    }
  });

  it("the simulation's sample-size field explains itself in its label", async () => {
    silenceNetwork();
    serveDatasets(api);
    vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
    render(<SimulationPanel kindOptions={PROTEIN} />);
    await waitFor(() => expect(screen.getByText("Replicates per group (0 = observed, 2-100 fixed)")).toBeTruthy());
    expect(pageText()).not.toContain("Use 0 for each row's observed replicate counts");
  });

  it("the phosphoprotein regulation options have no score explanation box", async () => {
    silenceNetwork();
    serveDatasets(api);
    vi.mocked(api.getPhosphoOptions).mockResolvedValue({
      conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: false,
      availableDataSources: ["data"], defaultDataSource: "data",
    } as unknown as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
    render(<PhosphoSpecificPage activeTab="phosprotRegulation" />);
    await waitFor(() => expect(screen.getAllByText(/Condition/).length).toBeGreaterThan(0));
    expect(pageText()).not.toContain("coordinates sum the log2 fold changes");
  });

  it("the advanced panel says in each label what a grey line under it used to", () => {
    const every: AdvancedPlotVisibleControls = {
      textElements: true, tickControls: true, legendControls: true, referenceLineColor: true, fontControls: true,
      boxplotStyle: true, boxplotOutliers: true, boxplotPoints: true, markerStyle: true, conditionMarkers: true,
      volcanoMarkers: true, rowLabels: true, valueLabels: true, correlationGradient: true,
    };
    const { container } = render(
      <AdvancedPlotOptions value={{}} onChange={() => {}} conditionOptions={["A"]} visibleControls={every} />
    );
    for (const gone of ["Reference: ", "Ref: ", "Diameter in points", "0 draws no outline", "Static plot only", "0 to 1. Reference"]) {
      expect(pageText()).not.toContain(gone);
    }
    // The hint style that rendered under a control, as opposed to the row
    // labels and in-card paragraphs that share its colour.
    expect(container.querySelectorAll("span.mt-1.block.text-slate-500").length).toBe(0);
    for (const label of ["Dot size (pt)", "Dot outline width (0 = none)", "Hit label size (static plot)"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });
});

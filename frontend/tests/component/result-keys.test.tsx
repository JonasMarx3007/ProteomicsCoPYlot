/**
 * A panel shows the result it stored, and only for the request that produced it.
 *
 * Each analysis panel keeps one result under a key and shows it only while the
 * key matches the request on screen. The ANOVA panel's request once gained the
 * post-hoc pair and its key did not, so a Tukey result could never match the key
 * it had been stored under: the panel said "Running the ANOVA and the Tukey HSD
 * post-hoc..." for as long as anyone waited, over an answer that had arrived.
 * The opposite drift shows a stale answer: a field that changes the request but
 * not the key leaves the old result up while the new one is computed.
 *
 * Each panel is mounted with every non-default setting its request carries, so
 * a field missing from the key is a field that changes nothing here; the answer
 * must appear, and a changed setting must take it down until the new one
 * arrives. These replace a comparison of object literals in the source.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnovaPanel } from "../../src/features/stats/AnovaPanel";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { SimulationPanel } from "../../src/features/stats/SimulationPanel";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import * as api from "../../src/lib/api";
import type { StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "./apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const MARKER = "the stored answer is on screen";
const PROTEIN = [{ value: "protein", label: "Protein" }];
const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B", "C"],
  samplesByCondition: { A: ["a1", "a2", "a3"], B: ["b1", "b2", "b3"], C: ["c1", "c2", "c3"] }, pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }],
  warnings: [], availableDataSources: ["data"], defaultDataSource: "data",
};
const COUNTS = { searchSpace: 1, overlapTested: 1, passingCutoff: 0, displayed: 0 };

type Case = {
  name: string;
  storageKey: string;
  saved: Record<string, unknown>;
  element: () => ReactElement;
  run: () => ReturnType<typeof vi.fn>;
  response: Record<string, unknown>;
  /** One setting change that alters the request. */
  change: () => void;
};

function setNumber(label: string, value: string) {
  const input = screen.getByLabelText(label, { selector: "input" });
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
}

const CASES: Case[] = [
  {
    name: "ANOVA with a Tukey post-hoc pair",
    storageKey: "stats.anova.v1",
    saved: {
      pValueThreshold: 0.01, useUncorrected: true, nClusters: 3, clusterMethod: "ward",
      postHoc: "tukey", postHocCondition1: "A", postHocCondition2: "C",
    },
    element: () => <AnovaPanel kindOptions={PROTEIN} />,
    run: () => vi.mocked(api.runAnovaAnalysis),
    response: {
      kind: "protein", source: "anova", sourceUsed: "data", labelColumn: "ProteinNames", totalRows: 1,
      significantCount: 0, clusterCount: null, completenessNotice: null, rows: [], clusterRows: [],
      postHocMethod: "tukey", postHocRows: [], postHocSignificantCount: 0, postHocComparison: "A vs C",
      warnings: [MARKER],
    },
    change: () => setNumber("P-value threshold", "0.02"),
  },
  {
    name: "volcano",
    storageKey: "stats.volcano.v1",
    saved: { condition1: "A", condition2: "C", pValueThreshold: 0.01, log2fcThreshold: 2, useUncorrected: true },
    element: () => <VolcanoPanel kindOptions={PROTEIN} />,
    run: () => vi.mocked(api.runVolcanoAnalysis),
    response: {
      kind: "protein", sourceUsed: "data", labelColumn: "ProteinNames", totalRows: 1, upregulatedCount: 0,
      downregulatedCount: 0, notSignificantCount: 1, rows: [], warnings: [MARKER],
    },
    change: () => setNumber("P-value threshold", "0.02"),
  },
  {
    name: "ORA",
    storageKey: "stats.ora.v1",
    saved: {
      condition1: "A", condition2: "C", pValueThreshold: 0.01, log2fcThreshold: 2, useUncorrected: true,
      adjPValueCutoff: 0.1, topN: 7, minTermSize: 4, maxTermSize: 300, backgroundMode: "global",
    },
    element: () => <OraPanel kindOptions={PROTEIN} />,
    run: () => vi.mocked(api.runEnrichmentAnalysis),
    response: {
      kind: "protein", sourceUsed: "data", selectedCluster: null, clusterGenes: [], clusterTerms: [],
      upGenes: [], downGenes: [], upTerms: [], downTerms: [], backgroundMode: "global", backgroundGenes: [],
      backgroundSize: 0, annotatedBackgroundSize: 0, organism: "hsapiens", correctionMethod: "fdr_bh",
      upstreamCorrectionMethod: "fdr_bh", databaseSha256: "", testedTermCount: 0,
      termCounts: { up: COUNTS, down: COUNTS, cluster: COUNTS }, warnings: [MARKER],
    },
    change: () => setNumber("P-value threshold", "0.02"),
  },
  {
    name: "replicate and variance projection",
    storageKey: "stats.simulation.v1",
    saved: { condition1: "A", condition2: "C", pValueThreshold: 0.01, log2fcThreshold: 2, sampleSizeOverride: 5 },
    element: () => <SimulationPanel kindOptions={PROTEIN} />,
    run: () => vi.mocked(api.runSimulationAnalysis),
    response: {
      kind: "protein", sourceUsed: "data", testType: "unpaired", condition1: "A", condition2: "C",
      sampleSizeMode: "override", sampleSizeOverride: 5, effectiveSampleSizeCondition1Min: 5,
      effectiveSampleSizeCondition1Max: 5, effectiveSampleSizeCondition2Min: 5, effectiveSampleSizeCondition2Max: 5,
      labelColumn: "ProteinNames", totalRows: 1, upregulatedCount: 0, downregulatedCount: 0, notSignificantCount: 1,
      rows: [], warnings: [MARKER],
    },
    change: () => setNumber("P-value threshold", "0.02"),
  },
];

beforeEach(() => {
  sessionStorage.clear();
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
});

describe.each(CASES)("the $name panel", ({ storageKey, saved, element, run, response, change }) => {
  it("shows the answer it stored for the request on screen", async () => {
    sessionStorage.setItem(`pcopylot.ui.${storageKey}`, JSON.stringify(saved));
    run().mockResolvedValue(response);
    render(element());
    await waitFor(() => expect(run()).toHaveBeenCalled(), { timeout: 4000 });
    await waitFor(() => expect(screen.getAllByText(MARKER).length).toBeGreaterThan(0));
  });

  it("takes the answer down when a setting changes, until the new one arrives", async () => {
    sessionStorage.setItem(`pcopylot.ui.${storageKey}`, JSON.stringify(saved));
    // Answered until the setting changes; the request after it never returns.
    let answering = true;
    run().mockImplementation(() => (answering ? Promise.resolve(response) : new Promise(() => {})));
    render(element());
    await waitFor(() => expect(screen.getAllByText(MARKER).length).toBeGreaterThan(0), { timeout: 4000 });
    answering = false;
    await act(async () => change());
    expect(screen.queryAllByText(MARKER)).toEqual([]);
  });
});

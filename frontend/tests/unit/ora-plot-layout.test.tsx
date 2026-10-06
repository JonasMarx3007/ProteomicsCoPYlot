/**
 * The two ORA figures are wide, separately downloadable and sized as asked.
 *
 * They are the page's only two plots a reader compares with each other, and
 * what they need most is width: a term label is a sentence, not a word. So the
 * up and down figures are stacked rather than in two columns, each has its own
 * export control, each is titled by the first condition alone (the direction
 * belongs to it), and the size row reaches the request and is remembered with
 * the panel -- each one `className` or one forgotten prop away from going back.
 *
 * The panel is mounted with a finished analysis. This replaced regular
 * expressions over OraPanel.tsx's JSX.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OraPanel } from "../../src/features/stats/OraPanel";
import * as api from "../../src/lib/api";
import type { EnrichmentResultResponse, StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["Treated", "Vehicle"],
  samplesByCondition: { Treated: ["t1", "t2"], Vehicle: ["v1", "v2"] }, pairIdsBySample: {},
  // ORA needs gene names to look terms up by.
  availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }], warnings: [],
  availableDataSources: ["data"], defaultDataSource: "data",
};
const TERM = {
  source: "BP", termId: "GO:1", name: "a process", termSize: 10, intersectionSize: 2, querySize: 5,
  geneRatio: 0.4, hitPercent: 20, pValue: 0.001, adjPValue: 0.01, intersectingGenes: ["G1", "G2"],
};
const COUNTS = { searchSpace: 100, overlapTested: 20, passingCutoff: 1, displayed: 1 };
const RESULT = {
  kind: "protein", sourceUsed: "data", selectedCluster: null, clusterGenes: [], clusterTerms: [],
  upGenes: ["G1", "G2"], downGenes: ["G3"], upTerms: [TERM], downTerms: [TERM], backgroundMode: "experiment",
  backgroundGenes: ["G1", "G2", "G3"], backgroundSize: 3, annotatedBackgroundSize: 3, organism: "hsapiens",
  correctionMethod: "fdr_bh", upstreamCorrectionMethod: "fdr_bh", testedTermCount: 20,
  termCounts: { up: COUNTS, down: COUNTS, cluster: COUNTS }, warnings: [],
} as unknown as EnrichmentResultResponse;

const UP = "Upregulated Terms in Treated";
const DOWN = "Downregulated Terms in Treated";

beforeEach(async () => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
  vi.mocked(api.runEnrichmentAnalysis).mockResolvedValue(RESULT);
  sessionStorage.setItem("pcopylot.ui.stats.ora.v1", JSON.stringify({ condition1: "Treated", condition2: "Vehicle" }));
  render(<OraPanel kindOptions={[{ value: "protein", label: "Protein" }]} />);
  await waitFor(() => expect(api.runEnrichmentAnalysis).toHaveBeenCalled(), { timeout: 3000 });
  await screen.findByText(UP, {}, { timeout: 4000 });
});

/** The section that holds a figure, found by its title. */
const section = (title: string) => screen.getByText(title).closest("section")!;

function plotRequest(direction: "up" | "down") {
  const urls = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
    .filter((url) => url.pathname.endsWith(`/ora/${direction}.png`));
  return urls.at(-1);
}

describe("the ORA figures", () => {
  it("are stacked one above the other, not placed side by side", () => {
    const shared = section(UP).parentElement!;
    expect(section(DOWN).parentElement).toBe(shared);
    expect(shared.className).not.toMatch(/grid-cols-2/);
    expect(shared.className).toMatch(/space-y-/);
  });

  it("each carry their own download control", () => {
    for (const [title, filename] of [[UP, /^ora_up_.*\.png$/], [DOWN, /^ora_down_.*\.png$/]] as const) {
      expect(screen.getByLabelText(`${title} download format`)).toBeTruthy();
      const download = Array.from(section(title).querySelectorAll("a[download]"));
      expect(download.length, title).toBe(1);
      expect(download[0].getAttribute("download")).toMatch(filename);
    }
  });

  it("name the first condition in their titles and not the second", () => {
    for (const title of [UP, DOWN]) {
      const heading = section(title).querySelector("h3")!.textContent!;
      expect(heading).toContain("Treated");
      expect(heading).not.toContain("Vehicle");
    }
  });

  it("request the size the page asks for", async () => {
    await waitFor(() => expect(plotRequest("up")).toBeDefined());
    for (const key of ["widthCm", "heightCm", "dpi"]) expect(plotRequest("up")!.searchParams.has(key), key).toBe(true);
    const width = screen.getByLabelText("Width (cm)");
    fireEvent.change(width, { target: { value: "31" } });
    fireEvent.blur(width);
    await waitFor(() => expect(plotRequest("up")!.searchParams.get("widthCm")).toBe("31"));
    await waitFor(() => expect(plotRequest("down")!.searchParams.get("widthCm")).toBe("31"));
  });

  it("remember their size and export format with the rest of the panel", async () => {
    const width = screen.getByLabelText("Width (cm)");
    fireEvent.change(width, { target: { value: "31" } });
    fireEvent.blur(width);
    fireEvent.change(screen.getByLabelText(`${UP} download format`), { target: { value: "svg" } });
    await waitFor(() => {
      const saved = JSON.parse(sessionStorage.getItem("pcopylot.ui.stats.ora.v1")!);
      expect(saved).toMatchObject({ widthCm: 31, downloadFormat: "svg" });
      expect(saved).toHaveProperty("heightCm");
      expect(saved).toHaveProperty("dpi");
    });
  });
});

/**
 * Every plot offered as a static/interactive pair follows one rule
 * (src/lib/plotRenderType.ts):
 *
 *   static      -> width, height and DPI, plus the PNG/JPG/WEBP/SVG/PDF export;
 *   interactive -> neither; Plotly's camera button and "Open ... Plot" in a new
 *                  window, and the static figure's size is not sent to it.
 *
 * Each pair is mounted in both types, and what is on screen and what is
 * requested is read. This replaced a node --test file that walked the pages'
 * TypeScript syntax trees for the `SizeRow` element and the ternary around it.
 */
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ComparisonPipelinePage from "../../src/features/comparison/ComparisonPipelinePage";
import PeptideLevelPage from "../../src/features/peptide/PeptideLevelPage";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import * as api from "../../src/lib/api";
import type { StatisticalOptionsResponse, VolcanoResultResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const STATS_OPTIONS: StatisticalOptionsResponse = {
  kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] }, pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }], warnings: [],
  availableDataSources: ["data"], defaultDataSource: "data",
};
const VOLCANO = {
  kind: "protein", sourceUsed: "data", totalRows: 1, upregulatedCount: 0, downregulatedCount: 0,
  notSignificantCount: 1, rows: [{ ProteinNames: "P1", log2FC: 0.1, pval: 0.5 }], warnings: [],
} as unknown as VolcanoResultResponse;

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getQcPlotOptions).mockResolvedValue({
    conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
    availableDataSources: ["data"], defaultDataSource: "data", centredPhosprotValues: false,
  } as Awaited<ReturnType<typeof api.getQcPlotOptions>>);
  vi.mocked(api.getComparisonOptions).mockResolvedValue({
    samples: ["a1", "b1"], conditions: ["A", "B"], sampleCount: 2, conditionCount: 2,
    dataSource: "data", filteredAvailable: false, imputedAvailable: false,
  });
  vi.mocked(api.getPeptideOverview).mockResolvedValue({
    filename: "peptides.tsv", path: "peptides.tsv", rows: 10, columns: 4, columnNames: ["Sequence", "a1", "b1"],
    availableSamples: ["a1", "b1"], availableProteins: ["P1"], metadataLoaded: true, metadataFilename: "meta.tsv", warnings: [],
  } as unknown as Awaited<ReturnType<typeof api.getPeptideOverview>>);
  vi.mocked(api.getStatisticalOptions).mockResolvedValue(STATS_OPTIONS);
  vi.mocked(api.runVolcanoAnalysis).mockResolvedValue(VOLCANO);
});

type Pair = {
  name: string;
  /** Seed the saved panel state that selects the render type, then mount. */
  mount: (type: "Normal" | "Interactive") => ReactElement;
  /** The plot request, without its extension. */
  path: RegExp;
};

const saved = (key: string, value: unknown) => sessionStorage.setItem(`pcopylot.ui.${key}`, JSON.stringify(value));

const PAIRS: Pair[] = [
  {
    name: "volcano",
    mount: (type) => { saved("stats.volcano.v1", { renderType: type, condition1: "A", condition2: "B" }); return <VolcanoPanel kindOptions={[{ value: "protein", label: "Protein" }]} />; },
    path: /\/api\/plots\/stats\/protein\/volcano\.(png|html)/,
  },
  {
    name: "QC PCA",
    mount: (type) => { saved("qc.pipeline.v1", { pca: { type } }); return <QCPipelinePage activeTab="pca" />; },
    path: /\/api\/plots\/qc\/protein\/pca(-interactive)?\.(png|html)/,
  },
  {
    name: "QC abundance",
    mount: (type) => { saved("qc.pipeline.v1", { abundance: { type } }); return <QCPipelinePage activeTab="abundance" />; },
    path: /\/api\/plots\/qc\/protein\/abundance(-interactive)?\.(png|html)/,
  },
  {
    name: "Pearson",
    mount: (type) => { saved("comparison.pipeline.v1", { pearson: { type, sample1: "a1", sample2: "b1" } }); return <ComparisonPipelinePage activeTab="pearson" />; },
    path: /\/api\/plots\/comparison\/protein\/pearson\.(png|html)/,
  },
  {
    name: "peptide RT",
    mount: (type) => { saved("peptide.level.v1", { rt: { type } }); return <PeptideLevelPage activeTab="rtPlot" />; },
    path: /\/api\/plots\/peptide\/rt(-interactive)?\.(png|html)/,
  },
];

/** Every plot URL the page asked for or framed. */
function plotRequests(path: RegExp): string[] {
  const fetched = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
  const framed = Array.from(document.querySelectorAll("iframe[src], img[src]")).map((element) => element.getAttribute("src") ?? "");
  return [...fetched, ...framed].filter((url) => path.test(url));
}

async function plotRequest(path: RegExp) {
  await waitFor(() => expect(plotRequests(path).length).toBeGreaterThan(0), { timeout: 4000 });
  return new URL(plotRequests(path).at(-1)!, "http://localhost");
}

const SIZE_KEYS = ["widthCm", "heightCm", "dpi"];

describe.each(PAIRS)("$name", ({ mount, path }) => {
  it("shows the size row and sends the size for the static plot", async () => {
    render(mount("Normal"));
    const url = await plotRequest(path);
    expect(url.pathname).toMatch(/\.png$/);
    for (const key of SIZE_KEYS) expect(url.searchParams.has(key), key).toBe(true);
    expect(screen.getAllByText("Width (cm)").length).toBe(1);
    expect(screen.getAllByText("DPI").length).toBe(1);
  });

  it("offers no size and sends none for the interactive plot", async () => {
    render(mount("Interactive"));
    const url = await plotRequest(path);
    expect(url.pathname).toMatch(/\.html$/);
    for (const key of SIZE_KEYS) expect(url.searchParams.has(key), key).toBe(false);
    expect(screen.queryByText("Width (cm)")).toBeNull();
    expect(screen.queryByText("DPI")).toBeNull();
  });
});

describe("the static volcano", () => {
  it("has an export control for its figure", async () => {
    render(PAIRS[0].mount("Normal"));
    await plotRequest(PAIRS[0].path);
    expect(await screen.findByLabelText("Volcano Plot download format", {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText("Download Plot").getAttribute("href")).toMatch(/volcano\.png/);
  });
});

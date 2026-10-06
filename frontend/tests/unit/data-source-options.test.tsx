/**
 * A data-source selector offers what the backend says exists, and nothing else.
 *
 * "data" is the annotated matrix, "filtered" and "imputed" exist only once the
 * user made them, and the backend reports which do (`availableDataSources`).
 * Every choosing page builds its list from that answer through
 * `dataSourceOptions`, so no page can offer a matrix the request would then be
 * refused for. QC describes the data as loaded and offers no choice -- PCA is
 * the one exception -- and Comparison is QC.
 *
 * The rule, its history and the backend half are in
 * tests/unit/data/test_one_data_source_vocabulary.py. This replaced the
 * Python checks there that searched types.ts and the panels' source for
 * `dataSourceOptions(` and `if (available.includes(saved)) return saved;`.
 */
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ComparisonPipelinePage from "../../src/features/comparison/ComparisonPipelinePage";
import KseaPage from "../../src/features/phospho/KseaPage";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import SingleProteinPage from "../../src/features/single-protein/SingleProteinPage";
import { AnovaPanel } from "../../src/features/stats/AnovaPanel";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { PathwayHeatmapPanel } from "../../src/features/stats/PathwayHeatmapPanel";
import { SimulationPanel } from "../../src/features/stats/SimulationPanel";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import * as api from "../../src/lib/api";
import { DATA_SOURCE_LABELS, resolveDataSource, type DataSource, type StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const PROTEIN = [{ value: "protein", label: "Protein" }];

function serve(available: DataSource[]) {
  const ladder = { availableDataSources: available, defaultDataSource: available.at(-1)! };
  vi.mocked(api.getStatisticalOptions).mockResolvedValue({
    kind: "protein", sourceUsed: "data", imputedAvailable: available.includes("imputed"),
    availableConditions: ["A", "B"], samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] }, pairIdsBySample: {},
    availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }], warnings: [], ...ladder,
  } as StatisticalOptionsResponse);
  vi.mocked(api.getQcPlotOptions).mockResolvedValue({
    conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"], centredPhosprotValues: false, ...ladder,
  } as Awaited<ReturnType<typeof api.getQcPlotOptions>>);
  vi.mocked(api.getSingleProteinOptions).mockResolvedValue({
    proteins: ["P1"], conditions: ["A", "B"], proteinCount: 1, conditionCount: 2, identifier: "workflow",
    availableIdentifiers: [{ key: "workflow", label: "Protein" }], dataSource: "data", ...ladder,
  } as Awaited<ReturnType<typeof api.getSingleProteinOptions>>);
  vi.mocked(api.getPhosphoOptions).mockResolvedValue({
    conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: false, ...ladder,
  } as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
  vi.mocked(api.getComparisonOptions).mockResolvedValue({
    samples: ["a1", "b1"], conditions: ["A", "B"], sampleCount: 2, conditionCount: 2,
    dataSource: "data", filteredAvailable: true, imputedAvailable: true,
  });
}

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
});

const CHOOSING: [string, string, () => ReactElement][] = [
  ["the volcano panel", "Data Source", () => <VolcanoPanel kindOptions={PROTEIN} />],
  ["the ANOVA panel", "Data Source", () => <AnovaPanel kindOptions={PROTEIN} />],
  ["the ORA panel", "Data Source", () => <OraPanel kindOptions={PROTEIN} />],
  ["the pathway heatmap panel", "Data source", () => <PathwayHeatmapPanel kindOptions={PROTEIN} />],
  ["the simulation panel", "Data Source", () => <SimulationPanel kindOptions={PROTEIN} />],
  ["the QC PCA", "Data Source", () => <QCPipelinePage activeTab="pca" />],
  ["the single-protein page", "Data source", () => <SingleProteinPage activeTab="boxplot" />],
  ["the Kinase Library page", "Data Source", () => <KseaPage />],
];

async function offered(label: string) {
  const select = (await screen.findByLabelText(label, {}, { timeout: 3000 })) as HTMLSelectElement;
  await waitFor(() => expect(select.options.length).toBeGreaterThan(1));
  // By label: the QC page keys its options by label rather than by value.
  return Array.from(select.options).map((option) => option.textContent);
}

describe.each(CHOOSING)("%s", (_name, label, element) => {
  it("offers exactly the matrices the backend reports", async () => {
    serve(["data", "filtered"]);
    render(element());
    expect(await offered(label)).toEqual(["data", "filtered"].map((source) => DATA_SOURCE_LABELS[source as DataSource]));
  });

  it("offers the imputed matrix once it exists", async () => {
    serve(["data", "filtered", "imputed"]);
    render(element());
    expect(await offered(label)).toEqual(["data", "filtered", "imputed"].map((source) => DATA_SOURCE_LABELS[source as DataSource]));
  });
});

describe("the pages that describe the data as loaded", () => {
  it("offer no data source on Comparison, which is QC", async () => {
    serve(["data", "filtered", "imputed"]);
    render(<ComparisonPipelinePage activeTab="pearson" />);
    await waitFor(() => expect(api.getComparisonOptions).toHaveBeenCalled());
    await screen.findAllByText(/Pearson/);
    expect(screen.queryByLabelText(/^Data [sS]ource$/)).toBeNull();
  });

  it("offer no data source on a QC plot other than the PCA", async () => {
    serve(["data", "filtered", "imputed"]);
    render(<QCPipelinePage activeTab="cv" />);
    await screen.findByText("Advanced Plot Options", {}, { timeout: 3000 });
    expect(screen.queryByLabelText(/^Data [sS]ource$/)).toBeNull();
  });
});

describe("restoring a saved choice", () => {
  it("keeps a deliberate choice that still exists rather than upgrading it", () => {
    const ladder = { availableDataSources: ["data", "filtered", "imputed"] as DataSource[], defaultDataSource: "imputed" as DataSource };
    expect(resolveDataSource("filtered", ladder)).toBe("filtered");
    expect(resolveDataSource("data", ladder)).toBe("data");
    expect(resolveDataSource("gone", ladder)).toBe("imputed");
    expect(resolveDataSource(null, ladder)).toBe("imputed");
  });
});

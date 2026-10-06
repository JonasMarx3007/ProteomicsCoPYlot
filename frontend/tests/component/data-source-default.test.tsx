/**
 * Panels open on the backend's default data source until the user chooses.
 *
 * Every selector used to open on "Data" on projects whose backend reported
 * `defaultDataSource: "imputed"`: the panels initialised their state to "data"
 * before the options arrived, and a made-up choice is indistinguishable from a
 * real one. These mount each panel with a backend that serves the ladder and
 * check what the selector shows -- replacing scans of the source for the
 * offending call patterns.
 */
import { StrictMode, type ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/lib/api";
import type { StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "./apiMock";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import { AnovaPanel } from "../../src/features/stats/AnovaPanel";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { PathwayHeatmapPanel } from "../../src/features/stats/PathwayHeatmapPanel";
import { SimulationPanel } from "../../src/features/stats/SimulationPanel";
import SingleProteinPage from "../../src/features/single-protein/SingleProteinPage";
import PhosphoSpecificPage from "../../src/features/phospho/PhosphoSpecificPage";
import KseaPage from "../../src/features/phospho/KseaPage";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein",
  sourceUsed: "imputed",
  imputedAvailable: true,
  availableConditions: ["A", "B"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] },
  pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }],
  warnings: [],
  availableDataSources: ["data", "filtered", "imputed"],
  defaultDataSource: "imputed",
};
const PROTEIN = [{ value: "protein", label: "Protein" }];

function mount(element: ReactElement) {
  return render(<StrictMode>{element}</StrictMode>);
}

async function dataSourceShown(label = "Data Source") {
  const select = await screen.findByLabelText(label);
  await waitFor(() => expect((select as HTMLSelectElement).options.length).toBeGreaterThan(1));
  return (select as HTMLSelectElement).value;
}

beforeEach(() => {
  silenceNetwork();
});

const STATS_PANELS: { name: string; storage: string; label: string; element: () => ReactElement }[] = [
  { name: "volcano", storage: "stats.volcano.v1", label: "Data Source", element: () => <VolcanoPanel kindOptions={PROTEIN} /> },
  { name: "ANOVA", storage: "stats.anova.v1", label: "Data Source", element: () => <AnovaPanel kindOptions={PROTEIN} /> },
  { name: "ORA", storage: "stats.ora.v1", label: "Data Source", element: () => <OraPanel kindOptions={PROTEIN} /> },
  { name: "pathway heatmap", storage: "stats.pathwayHeatmap.v1", label: "Data source", element: () => <PathwayHeatmapPanel kindOptions={PROTEIN} /> },
  { name: "simulation", storage: "stats.simulation.v1", label: "Data Source", element: () => <SimulationPanel kindOptions={PROTEIN} /> },
];

describe.each(STATS_PANELS)("the $name panel", ({ storage, label, element }) => {
  it("opens on the served default when nothing was saved", async () => {
    vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
    mount(element());
    await waitFor(async () => expect(await dataSourceShown(label)).toBe("imputed"));
  });

  it("keeps a saved choice that is still available", async () => {
    window.sessionStorage.setItem(`pcopylot.ui.${storage}`, JSON.stringify({ dataSource: "filtered" }));
    vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
    mount(element());
    await waitFor(async () => expect(await dataSourceShown(label)).toBe("filtered"));
  });

  it("falls back to the default when the saved matrix is gone", async () => {
    window.sessionStorage.setItem(`pcopylot.ui.${storage}`, JSON.stringify({ dataSource: "imputed" }));
    vi.mocked(api.getStatisticalOptions).mockResolvedValue({
      ...OPTIONS, availableDataSources: ["data", "filtered"], defaultDataSource: "filtered", imputedAvailable: false,
    });
    mount(element());
    await waitFor(async () => expect(await dataSourceShown(label)).toBe("filtered"));
  });
});

// --- the pages that load their own options ------------------------------------

const LADDER = { availableDataSources: ["data", "filtered", "imputed"], defaultDataSource: "imputed" } as const;

const PAGES: { name: string; label: string; serve: () => void; element: () => ReactElement }[] = [
  {
    name: "single-protein page",
    label: "Data source",
    serve: () => vi.mocked(api.getSingleProteinOptions).mockResolvedValue({
      proteins: ["P1"], conditions: ["A", "B"], proteinCount: 1, conditionCount: 2, identifier: "workflow",
      availableIdentifiers: [{ key: "workflow", label: "Protein" }], dataSource: "data", ...LADDER,
      availableDataSources: [...LADDER.availableDataSources],
    }),
    element: () => <SingleProteinPage activeTab="boxplot" />,
  },
  {
    name: "phosphosite page",
    label: "Data Source",
    serve: () => vi.mocked(api.getPhosphoOptions).mockResolvedValue({
      conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: true,
      ...LADDER, availableDataSources: [...LADDER.availableDataSources],
    }),
    element: () => <PhosphoSpecificPage activeTab="phosprotRegulation" />,
  },
  {
    name: "Kinase Library page",
    label: "Data Source",
    serve: () => vi.mocked(api.getPhosphoOptions).mockResolvedValue({
      conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: true,
      ...LADDER, availableDataSources: [...LADDER.availableDataSources],
    }),
    element: () => <KseaPage />,
  },
];

describe.each(PAGES)("the $name", ({ label, serve, element }) => {
  it("opens on the served default when nothing was saved", async () => {
    serveDatasets(api);
    serve();
    mount(element());
    await waitFor(async () => expect(await dataSourceShown(label)).toBe("imputed"));
  });
});

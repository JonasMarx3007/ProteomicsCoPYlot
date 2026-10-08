/**
 * Phosphoprotein volcano plots cannot be added to the report.
 *
 * The report has protein and phospho volcano sections only; an entry of kind
 * "phosprot" was accepted by the panel and then dropped by the report in
 * silence. The panel now offers no Add/Remove buttons for that kind and says
 * why, while protein and phospho keep theirs.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import * as api from "../../src/lib/api";
import type { StatisticalOptionsResponse, VolcanoResultResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const options = (kind: string): StatisticalOptionsResponse => ({
  kind, sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] }, pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }], warnings: [],
  availableDataSources: ["data"], defaultDataSource: "data",
} as StatisticalOptionsResponse);

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getStatisticalOptions).mockImplementation(async (kind) => options(String(kind)));
  vi.mocked(api.runVolcanoAnalysis).mockResolvedValue({
    kind: "protein", sourceUsed: "data", totalRows: 1, upregulatedCount: 0, downregulatedCount: 0,
    notSignificantCount: 1, rows: [{ ProteinNames: "P1", log2FC: 0.1, pval: 0.5 }], warnings: [],
  } as unknown as VolcanoResultResponse);
  sessionStorage.setItem("pcopylot.ui.stats.volcano.v1", JSON.stringify({ condition1: "A", condition2: "B" }));
});

it("offers no report buttons for phosphoprotein volcanoes and says why", async () => {
  render(<VolcanoPanel kindOptions={[{ value: "phosprot", label: "Phosphoprotein" }]} />);
  await waitFor(() => expect(screen.getByText("Phosphoprotein volcano plots cannot be added to the report.")).toBeTruthy());
  expect(screen.queryByRole("button", { name: "Add Volcano To Report" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Remove Volcano From Report" })).toBeNull();
});

it.each(["protein", "phospho"])("keeps the report buttons for %s volcanoes", async (kind) => {
  render(<VolcanoPanel kindOptions={[{ value: kind, label: kind }]} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Add Volcano To Report" })).toBeTruthy());
  expect(screen.getByRole("button", { name: "Remove Volcano From Report" })).toBeTruthy();
  expect(screen.queryByText("Phosphoprotein volcano plots cannot be added to the report.")).toBeNull();
});

/**
 * Choices restored from a saved session are validated before they are used.
 *
 * A value saved by an older build -- a test type or a cluster linkage that no
 * longer exists -- must fall back to the default rather than reach the backend,
 * and ORA must cluster with the same linkage the user sees. These mount the
 * panels instead of counting call sites in the source.
 */
import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/lib/api";
import type { StatisticalOptionsResponse } from "../../src/lib/types";
import { silenceNetwork } from "./apiMock";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import { AnovaPanel } from "../../src/features/stats/AnovaPanel";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { SimulationPanel } from "../../src/features/stats/SimulationPanel";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein",
  sourceUsed: "data",
  imputedAvailable: false,
  availableConditions: ["A", "B", "C"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"], C: ["c1", "c2"] },
  pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }],
  warnings: [],
  availableDataSources: ["data"],
  defaultDataSource: "data",
};
const PROTEIN = [{ value: "protein", label: "Protein" }];

function save(storage: string, state: Record<string, unknown>) {
  window.sessionStorage.setItem(`pcopylot.ui.${storage}`, JSON.stringify(state));
}

async function selected(label: string) {
  return ((await screen.findByLabelText(label)) as HTMLSelectElement).value;
}

beforeEach(() => {
  silenceNetwork();
  vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
});

describe("a saved test type that no longer exists", () => {
  it.each([
    ["volcano", "stats.volcano.v1", () => <VolcanoPanel kindOptions={PROTEIN} />],
    ["ORA", "stats.ora.v1", () => <OraPanel kindOptions={PROTEIN} />],
    ["simulation", "stats.simulation.v1", () => <SimulationPanel kindOptions={PROTEIN} />],
  ])("falls back to the unpaired test on the %s panel", async (_name, storage, element) => {
    save(storage, { testType: "mann_whitney" });
    render(<StrictMode>{element()}</StrictMode>);
    await waitFor(async () => expect(await selected("Test type")).toBe("unpaired"));
  });

  it("keeps a saved test type that still exists", async () => {
    save("stats.volcano.v1", { testType: "unpaired_welch" });
    render(<StrictMode><VolcanoPanel kindOptions={PROTEIN} /></StrictMode>);
    await waitFor(async () => expect(await selected("Test type")).toBe("unpaired_welch"));
  });
});

describe("a saved cluster linkage", () => {
  it.each([
    // Each panel shows the linkage only in its clustering mode.
    ["ANOVA", "stats.anova.v1", "anova_cluster", () => <AnovaPanel kindOptions={PROTEIN} />],
    ["ORA", "stats.ora.v1", "anova", () => <OraPanel kindOptions={PROTEIN} />],
  ])("that no longer exists falls back to average linkage on the %s panel", async (_name, storage, sourceMode, element) => {
    save(storage, { clusterMethod: "centroid", sourceMode });
    render(<StrictMode>{element()}</StrictMode>);
    await waitFor(async () => expect(await selected("Cluster method")).toBe("average"));
  });
});

describe("ORA built on ANOVA clusters", () => {
  it("clusters with the linkage it displays", async () => {
    save("stats.ora.v1", { sourceMode: "anova", clusterMethod: "ward" });
    render(<StrictMode><OraPanel kindOptions={PROTEIN} /></StrictMode>);
    expect(await selected("Cluster method")).toBe("ward");
    await waitFor(() => expect(api.runAnovaAnalysis).toHaveBeenCalled(), { timeout: 3000 });
    const request = vi.mocked(api.runAnovaAnalysis).mock.calls.at(-1)![0];
    expect(request).toMatchObject({ source: "anova_cluster", clusterMethod: "ward" });
  });
});

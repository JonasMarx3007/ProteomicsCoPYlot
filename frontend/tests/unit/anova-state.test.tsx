/**
 * The ANOVA panel's controls survive a save, including a save older than them.
 *
 * Save state captures every key under `pcopylot.ui.`; a control the panel does
 * not write there is silently not saved. A state file written before a control
 * existed must still restore, each missing or malformed control falling back
 * to its default -- the backend's default, so that the request and the UI
 * agree -- and never to `undefined` or NaN, which reach the backend as a 422.
 * Clamped values stay inside the request schema's range.
 *
 * Defaults and ranges are read from `AnovaRequest` in the generated OpenAPI
 * schema; the panel is mounted with saved states. This replaced Python checks
 * over the source of the statistics panels, restoreUiState.ts and
 * persistedUiState.ts (tests/unit/stats/test_anova_colors_and_state.py keeps
 * the colour checks, which are the backend's).
 */
import { render, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnovaPanel } from "../../src/features/stats/AnovaPanel";
import { OraPanel } from "../../src/features/stats/OraPanel";
import { ANOVA_CLUSTER_METHOD_OPTIONS, restoreClusterCount, restoreClusterMethod, restorePValueThreshold } from "../../src/features/stats/statsHelpers";
import * as api from "../../src/lib/api";
import { captureCopylotSessionStorageState } from "../../src/lib/restoreUiState";
import type { StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

type Property = { default?: unknown; minimum?: number; maximum?: number; exclusiveMinimum?: number; enum?: string[] };
const ANOVA: Record<string, Property> = JSON.parse(readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8"))
  .components.schemas.AnovaRequest.properties;

const PROTEIN = [{ value: "protein", label: "Protein" }];
const KEY = "pcopylot.ui.stats.anova.v1";

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getStatisticalOptions).mockResolvedValue({
    kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B", "C"],
    samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"], C: ["c1", "c2"] }, pairIdsBySample: {},
    availableIdentifiers: [{ key: "workflow", label: "Protein" }, { key: "genes", label: "Genes" }], warnings: [],
    availableDataSources: ["data"], defaultDataSource: "data",
  } as StatisticalOptionsResponse);
});

/** What the panel saves after mounting on a given saved state. */
async function savedAfterMount(saved?: Record<string, unknown>, panel = <AnovaPanel kindOptions={PROTEIN} />, key = KEY) {
  if (saved) sessionStorage.setItem(key, JSON.stringify(saved));
  render(panel);
  let state: Record<string, unknown> = {};
  await waitFor(() => {
    state = JSON.parse(sessionStorage.getItem(key) ?? "{}");
    expect(state).toHaveProperty("nClusters");
  });
  return state;
}

// A state file from before clusterMethod, postHoc and the post-hoc pair existed.
const LEGACY = {
  kind: "protein", sourceMode: "anova_cluster", dataSource: "data", identifier: "workflow", pValueThreshold: 0.05,
  useUncorrected: false, showLegend: true, selectedCluster: "none",
};

describe("the ANOVA panel's saved state", () => {
  it("holds every control", async () => {
    const state = await savedAfterMount();
    for (const control of ["kind", "sourceMode", "dataSource", "identifier", "pValueThreshold", "useUncorrected",
      "showDendrograms", "selectedCluster", "nClusters", "clusterMethod", "postHoc", "postHocCondition1", "postHocCondition2"]) {
      expect(state, control).toHaveProperty(control);
    }
  });

  it("is captured by a save", async () => {
    await savedAfterMount();
    expect(captureCopylotSessionStorageState()).toHaveProperty(KEY);
  });

  it("restores each control missing from an older save to the backend's default", async () => {
    const state = await savedAfterMount(LEGACY);
    for (const control of ["clusterMethod", "nClusters", "postHoc", "showDendrograms", "pValueThreshold"]) {
      expect(state[control], control).toBe(ANOVA[control].default);
    }
    // No backend default: the UI's "no pair chosen".
    expect(state.postHocCondition1).toBe("");
    expect(state.postHocCondition2).toBe("");
  });

  it("restores malformed numbers to their defaults rather than NaN", async () => {
    const state = await savedAfterMount({ ...LEGACY, nClusters: "four", pValueThreshold: "x", clusterMethod: "nonsense" });
    expect(state.nClusters).toBe(ANOVA.nClusters.default);
    expect(state.pValueThreshold).toBe(ANOVA.pValueThreshold.default);
    expect(state.clusterMethod).toBe(ANOVA.clusterMethod.default);
  });

  it("clamps a saved cluster count into the request's range", async () => {
    expect((await savedAfterMount({ ...LEGACY, nClusters: 500 })).nClusters).toBe(ANOVA.nClusters.maximum);
  });

  it("is restored through the same guard by the ORA panel's cluster count", async () => {
    const state = await savedAfterMount({ nClusters: "four" }, <OraPanel kindOptions={PROTEIN} />, "pcopylot.ui.stats.ora.v1");
    expect(state.nClusters).toBe(ANOVA.nClusters.default);
  });
});

describe("the restore guards", () => {
  it("keep a cluster count inside the request schema's range", () => {
    expect(restoreClusterCount(0)).toBe(ANOVA.nClusters.minimum);
    expect(restoreClusterCount(101)).toBe(ANOVA.nClusters.maximum);
    expect(restoreClusterCount(undefined)).toBe(ANOVA.nClusters.default);
  });

  it("keep a p-value threshold inside the request schema's range", () => {
    expect(ANOVA.pValueThreshold.exclusiveMinimum).toBe(0);
    expect(restorePValueThreshold(0)).toBe(ANOVA.pValueThreshold.default);
    expect(restorePValueThreshold(1)).toBe(ANOVA.pValueThreshold.maximum);
    expect(restorePValueThreshold(1.01)).toBe(ANOVA.pValueThreshold.default);
  });

  it("offer exactly the linkage methods the request accepts", () => {
    expect(ANOVA_CLUSTER_METHOD_OPTIONS.map(({ value }) => value).sort()).toEqual([...ANOVA.clusterMethod.enum!].sort());
    expect(restoreClusterMethod(undefined)).toBe(ANOVA.clusterMethod.default);
  });
});

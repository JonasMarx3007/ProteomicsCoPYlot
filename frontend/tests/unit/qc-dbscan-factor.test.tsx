/**
 * DBSCAN's radius travels as a fraction of the median sample distance.
 *
 * An absolute radius means something different on PC scores (tens of log2
 * units), UMAP (a few units) and t-SNE (tens); the old absolute default of 0.5
 * labelled every sample "Noise" on any real projection. The factor is what the
 * page, the routes and the report carry (tests/unit/qc/test_dbscan_eps_is_relative.py).
 *
 * The routes are read from the generated OpenAPI schema and the PCA page's
 * request from a mounted page. This replaced a Python scan of every .ts/.tsx
 * file for the old parameter's spelling, which is an ESLint rule now
 * (eslint.config.js, GLOBAL_RULES).
 */
import { render, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const openapi = JSON.parse(readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8"));
const ABSOLUTE = /^dbscan_?eps$/i;

function routesTaking(match: (name: string) => boolean): string[] {
  return Object.entries(openapi.paths as Record<string, Record<string, { parameters?: { name: string }[] }>>)
    .filter(([, operations]) => Object.values(operations).some((operation) => (operation.parameters ?? []).some(({ name }) => match(name))))
    .map(([path]) => path).sort();
}

describe("the DBSCAN radius", () => {
  it("is taken as a factor by the three PCA routes, and by no other", () => {
    expect(routesTaking((name) => name === "dbscanEpsFactor")).toEqual([
      "/api/plots/qc/{kind}/pca-features", "/api/plots/qc/{kind}/pca-interactive.html", "/api/plots/qc/{kind}/pca.png",
    ]);
  });

  it("is not taken as an absolute radius by any route", () => {
    expect(routesTaking((name) => ABSOLUTE.test(name))).toEqual([]);
  });

  it("is sent by the PCA page as a factor", async () => {
    silenceNetwork();
    serveDatasets(api);
    vi.mocked(api.getQcPlotOptions).mockResolvedValue({
      conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
      availableDataSources: ["data"], defaultDataSource: "data", centredPhosprotValues: false,
    } as Awaited<ReturnType<typeof api.getQcPlotOptions>>);
    sessionStorage.setItem("pcopylot.ui.qc.pipeline.v1", JSON.stringify({ pca: { clusterMethod: "DBSCAN", colorBy: "Cluster", dbscanEpsFactor: 0.4 } }));
    render(<QCPipelinePage activeTab="pca" />);
    const requested = () => vi.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
      .filter((url) => /\/pca\.png$/.test(url.pathname));
    await waitFor(() => expect(requested().length).toBeGreaterThan(0));
    const query = requested().at(-1)!.searchParams;
    expect(query.get("dbscanEpsFactor")).toBe("0.4");
    expect([...query.keys()].filter((key) => ABSOLUTE.test(key))).toEqual([]);
  });
});

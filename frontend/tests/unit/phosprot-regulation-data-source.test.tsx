/**
 * The phosphoprotein-regulation plot runs on the data source the user picked.
 *
 * It sums significant phosphosite log2 fold changes from a volcano it computes
 * itself, which was hard-wired to the unfiltered, non-imputed matrix while the
 * Statistics volcano offered data / filtered / imputed -- so the two could
 * disagree on which sites are significant. The page now has one choice, and it
 * reaches the regulation plot, its table and the assistant's view of it. The
 * backend half is tests/unit/phospho/test_phosprot_regulation_data_source.py.
 *
 * This replaced a Python count of `dataSource: debouncedDataSource,` in
 * PhosphoSpecificPage.tsx; the page is mounted and the choice changed here.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PhosphoSpecificPage from "../../src/features/phospho/PhosphoSpecificPage";
import * as api from "../../src/lib/api";
import type { ContextMode } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getPhosphoOptions).mockResolvedValue({
    conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: false,
    availableDataSources: ["data", "filtered"], defaultDataSource: "filtered",
  } as unknown as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
});

/** The data source of the last regulation plot, table and context mode. */
function sent(modes: (ContextMode | null)[]) {
  const plot = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
    .filter((url) => url.pathname.endsWith("/phosprot-regulation.html")).at(-1);
  const table = vi.mocked(api.getPhosphoTable).mock.calls.filter(([tab]) => tab === "phosprotRegulation").at(-1);
  return {
    plot: plot?.searchParams.get("dataSource"),
    table: (table?.[1] as Record<string, unknown> | undefined)?.dataSource,
    context: (modes.at(-1) as Record<string, unknown> | null | undefined)?.dataSource,
  };
}

function mount(saved: Record<string, unknown> = {}) {
  sessionStorage.setItem("pcopylot.ui.phospho.specific.v1", JSON.stringify({
    phosprotRegulation: { condition1: "A", condition2: "B" }, ...saved,
  }));
  const modes: (ContextMode | null)[] = [];
  render(<PhosphoSpecificPage activeTab="phosprotRegulation" onContextModeChange={(mode) => modes.push(mode)} />);
  return modes;
}

describe("the phosphoprotein regulation", () => {
  it("sends the served default to the plot, the table and the assistant", async () => {
    const modes = mount();
    await waitFor(() => expect(sent(modes)).toEqual({ plot: "filtered", table: "filtered", context: "filtered" }), { timeout: 3000 });
  });

  it("never asks for the placeholder before the backend has said which matrices exist", async () => {
    // The page used to debounce the choice like a typed field, so its first
    // plot and table requests went out for "data" and were sent again 650 ms
    // later for the served default.
    const modes = mount();
    await waitFor(() => expect(sent(modes).plot).toBe("filtered"), { timeout: 3000 });
    const plots = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
      .filter((url) => url.pathname.endsWith("/phosprot-regulation.html"));
    expect(plots.map((url) => url.searchParams.get("dataSource"))).not.toContain("data");
    const tables = vi.mocked(api.getPhosphoTable).mock.calls.filter(([tab]) => tab === "phosprotRegulation");
    expect(tables.map(([, params]) => (params as Record<string, unknown>).dataSource)).not.toContain("data");
    expect(modes.map((mode) => (mode as Record<string, unknown> | null)?.dataSource)).not.toContain("data");
  });

  it("sends a changed choice to all three", async () => {
    const modes = mount();
    const select = (await screen.findByLabelText("Data Source")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("filtered"));
    fireEvent.change(select, { target: { value: "data" } });
    await waitFor(() => expect(sent(modes)).toEqual({ plot: "data", table: "data", context: "data" }), { timeout: 3000 });
  });

  it("restores a saved choice rather than the default", async () => {
    // A saved choice that is neither the default nor the page's placeholder.
    vi.mocked(api.getPhosphoOptions).mockResolvedValue({
      conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: true,
      availableDataSources: ["data", "filtered", "imputed"], defaultDataSource: "imputed",
    } as unknown as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
    const modes = mount({ dataSource: "filtered" });
    await waitFor(() => expect(sent(modes)).toEqual({ plot: "filtered", table: "filtered", context: "filtered" }), { timeout: 3000 });
  });
});

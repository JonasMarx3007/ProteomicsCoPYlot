/**
 * The S/T/Y plot counts phosphosites, and the page does not call it a peptide count.
 *
 * Each bar is a number of modified serine, threonine and tyrosine sites. The
 * page and the navigation once called it an "S/T/Y peptide count", which is a
 * different number (one peptide can carry several sites). The backend's
 * figure, table and exported notebook are checked in
 * tests/unit/phospho/test_sty_plot_counts_sites.py; this is the page, mounted.
 *
 * This replaced a Python search of every frontend file for the old wording.
 */
import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PhosphoSpecificPage from "../../src/features/phospho/PhosphoSpecificPage";
import * as api from "../../src/lib/api";
import { phosphoTabs } from "../../src/lib/navigationTabs";
import { serveDatasets } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

describe("the S/T/Y plot", () => {
  it("is not called a peptide count in the navigation", () => {
    const sty = phosphoTabs.find((tab) => tab.key === "sty");
    expect(sty).toBeDefined();
    expect(sty!.label.toLowerCase()).not.toContain("peptide");
  });

  it("is not called a peptide count on its page", async () => {
    serveDatasets(api);
    vi.mocked(api.getPhosphoOptions).mockResolvedValue({
      conditions: ["A", "B"], samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: false,
      availableDataSources: ["data"], defaultDataSource: "data",
    } as unknown as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
    // The figure is served, so the page draws it with its title as the alt text.
    vi.stubGlobal("fetch", vi.fn(async () => new Response("png", { status: 200, headers: { "Content-Type": "image/png" } })));
    URL.createObjectURL = vi.fn(() => "blob:sty");
    URL.revokeObjectURL = vi.fn();
    render(<PhosphoSpecificPage activeTab="sty" />);
    // The figure, once the page has settled on what it draws.
    await waitFor(() => expect(document.querySelector("img[src='blob:sty']")).not.toBeNull(), { timeout: 3000 });
    const text = (document.body.textContent ?? "").toLowerCase();
    expect(text).not.toContain("peptide count");
    const image = document.querySelector("img[src='blob:sty']")!;
    expect(image.getAttribute("alt")).toBe("STY Plot");
  });
});

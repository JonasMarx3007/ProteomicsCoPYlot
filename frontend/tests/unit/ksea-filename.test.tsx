/**
 * The Kinase Library download is named after the contrast it contains.
 *
 * Written by hand, the control-volcano file name said
 * `(cond2 - ctrl2) - (cond1 - ctrl1)` while the exported log2FC is the other way
 * round, so a saved file claimed the opposite sign to the numbers inside it.
 * The backend's `comparison_contrast` decides the orientation; both sides are
 * held to tests/fixtures/comparison_contrast.json, the backend by
 * tests/unit/report/test_report_version_and_ksea_filename.py and the page here.
 *
 * This replaced a Python regular expression over KseaPage.tsx; the page is
 * mounted with a control comparison and its download link read.
 */
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KseaPage from "../../src/features/phospho/KseaPage";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const CONTRAST = JSON.parse(readFileSync(resolve(__dirname, "../../../tests/fixtures/comparison_contrast.json"), "utf-8"));
const CONDITIONS = [CONTRAST.condition1, CONTRAST.condition2, CONTRAST.condition1Control, CONTRAST.condition2Control];

/** The contrast as a file name: "(a - b) - (c - d)" -> "(a-b)_minus_(c-d)". */
const asFilename = (contrast: string) => contrast.replaceAll(" - ", "-").replace(")-(", ")_minus_(");

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getPhosphoOptions).mockResolvedValue({
    conditions: CONDITIONS, samplesByCondition: {}, pairIdsBySample: {}, features: ["S1"], imputedAvailable: false,
    availableDataSources: ["data"], defaultDataSource: "data",
  } as unknown as Awaited<ReturnType<typeof api.getPhosphoOptions>>);
  vi.mocked(api.getPhosphoTable).mockResolvedValue({ rows: [{ site: "S1", log2FC: 1.5 }] } as unknown as Awaited<ReturnType<typeof api.getPhosphoTable>>);
});

async function downloadName(saved: Record<string, unknown>) {
  sessionStorage.setItem("pcopylot.ui.phospho.ksea.v1", JSON.stringify(saved));
  render(<KseaPage />);
  const link = await screen.findByText("Download Kinase Library Table (TSV)", {}, { timeout: 4000 });
  return link.getAttribute("download");
}

describe("the Kinase Library table download", () => {
  it("states the control contrast in the orientation the backend computes", async () => {
    const name = await downloadName({
      sourceMode: "volcano_control", condition1: CONTRAST.condition1, condition2: CONTRAST.condition2,
      condition1Control: CONTRAST.condition1Control, condition2Control: CONTRAST.condition2Control,
    });
    expect(name).toBe(`KinaseLibrary_${asFilename(CONTRAST.contrast)}.tsv`);
  });

  it("names a plain comparison by its two conditions in order", async () => {
    const name = await downloadName({ sourceMode: "volcano", condition1: CONTRAST.condition1, condition2: CONTRAST.condition2 });
    expect(name).toBe(`KinaseLibrary_${CONTRAST.condition1}_vs_${CONTRAST.condition2}.tsv`);
  });
});

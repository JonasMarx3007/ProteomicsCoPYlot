/**
 * The CV of a ratio is flagged under the figure, for that one dataset and tab.
 *
 * A `robust_site_median` phosphoprotein matrix holds ratios to each site's own
 * median, so its CV cannot be read next to the protein- or phosphosite-level
 * CVs. Only the backend knows how the matrix was made, so the QC options say so
 * (`centredPhosprotValues`, tests/unit/qc/test_cv_ratio_warning.py) and the CV
 * tab warns in a box under the figure -- never in the figure, where it would
 * travel into every export -- and nowhere else, because a warning that shows up
 * on plain abundances teaches people to ignore it.
 *
 * This replaced a Python check that compared string offsets in
 * QCPipelinePage.tsx; the page is mounted at each level and tab here.
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import * as api from "../../src/lib/api";
import { DATASETS, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const NOTICE = "Ratios, not abundances";

function serve(centred: boolean | "for every level") {
  silenceNetwork();
  vi.mocked(api.resetBrowserSessionState).mockResolvedValue(undefined);
  vi.mocked(api.getCurrentDatasets).mockResolvedValue({
    ...DATASETS, phosprot: { filename: "phosprot.tsv", rows: 10, columns: 6 },
  } as unknown as typeof DATASETS);
  vi.mocked(api.getQcPlotOptions).mockImplementation(async (kind) => ({
    conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
    availableDataSources: ["data"], defaultDataSource: "data",
    // The backend sets the flag for that one collapse at that one level.
    centredPhosprotValues: centred === "for every level" || (centred && kind === "phosprot"),
  }) as Awaited<ReturnType<typeof api.getQcPlotOptions>>);
}

async function mount(kind: string, tab: "cv" | "boxplot") {
  sessionStorage.setItem("pcopylot.ui.qc.pipeline.v1", JSON.stringify({ kind }));
  render(<QCPipelinePage activeTab={tab} />);
  const figure = await screen.findByText("Loading plot…", {}, { timeout: 3000 });
  // Let the options, which carry the flag, arrive before anything is read.
  await waitFor(() => expect(api.getQcPlotOptions).toHaveBeenCalledWith(kind, expect.anything()));
  await act(async () => {});
  return figure;
}

describe("the CV of a centred phosphoprotein matrix", () => {
  beforeEach(() => serve(true));

  it("is flagged in a box under the figure", async () => {
    const figure = await mount("phosprot", "cv");
    const notice = await screen.findByText(NOTICE);
    expect(figure.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // Beside the figure, not inside the element that shows it.
    expect(figure.contains(notice)).toBe(false);
  });

  it("is not flagged on another QC tab", async () => {
    await mount("phosprot", "boxplot");
    expect(screen.queryByText(NOTICE)).toBeNull();
  });

  it.each(["protein", "phospho"])("is not flagged at the %s level", async (kind) => {
    await mount(kind, "cv");
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe("a flag on another level", () => {
  it("does not flag the protein CV, so a stale flag from the phosphoprotein level cannot", async () => {
    serve("for every level");
    await mount("protein", "cv");
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

describe("the CV of a phosphoprotein matrix of abundances", () => {
  it("is not flagged", async () => {
    serve(false);
    await mount("phosprot", "cv");
    expect(screen.queryByText(NOTICE)).toBeNull();
  });
});

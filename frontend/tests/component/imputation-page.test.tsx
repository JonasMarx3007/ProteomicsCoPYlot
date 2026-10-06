/**
 * Imputation happens when the button is pressed, and at no other time.
 *
 * `runImputation` does not preview: it computes the imputation and stores it as
 * the session's imputed matrix, the one every other panel offers as "Imputed
 * Data". The page used to call it on every settings change, so typing a number
 * into Downshift and walking away replaced the matrix every volcano and PCA in
 * the session was about to use. The three plots are the preview: each draws
 * from the parameters in its own URL and never reads what is stored (the
 * backend half of that is tests/unit/data/test_imputation_preview_routes.py).
 *
 * These mount the page and watch which calls it makes, replacing a scan of
 * its source for which function called which.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ImputationPage from "../../src/features/data/ImputationPage";
import * as api from "../../src/lib/api";
import type { AnnotationImputationInfo, ImputationResultResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "./apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const STORED: AnnotationImputationInfo = {
  mode: "quantile", applied: true, qValue: 0.01, adjustStd: 0.3, downShift: 1.8, width: 0.3,
  seed: 42, sampleWise: true, sampleCount: 10, rowCount: 4321, missingBefore: 500, missingAfter: 0,
};

const RUN = {
  kind: "protein", method: "quantile", sourceUsed: "data", rows: 1234, columns: 12,
  sampleColumns: Array.from({ length: 10 }, (_, i) => `s${i}`), missingBefore: 300, missingAfter: 0,
  mean: null, std: null, quantile: null, qValue: 0.01, adjustStd: 0.3, downShift: 1.8, width: 0.3,
  seed: 7, sampleWise: true, beforeMissingHistogram: [], overallHistogram: [], normalFitCurve: [],
  afterImputationHistogram: [], warnings: [], preview: [],
} as unknown as ImputationResultResponse;

function serve(stored: AnnotationImputationInfo | null) {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getCurrentAnnotation).mockResolvedValue(
    { imputation: stored } as unknown as Awaited<ReturnType<typeof api.getCurrentAnnotation>>
  );
  vi.mocked(api.runImputation).mockResolvedValue(RUN);
}

function setNumber(label: string, value: string) {
  const input = screen.getByLabelText(label, { selector: "input" });
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
}

function plotUrls(): string[] {
  return Array.from(document.querySelectorAll("img")).map((image) => image.getAttribute("src") ?? "");
}

async function mount(stored: AnnotationImputationInfo | null) {
  serve(stored);
  render(<ImputationPage />);
  await waitFor(() => expect(plotUrls().length).toBe(3));
}

beforeEach(() => {
  sessionStorage.clear();
});

describe("the imputation page", () => {
  it("draws the preview before anything is applied, and says nothing is stored", async () => {
    await mount(null);
    const urls = plotUrls();
    expect(urls.some((url) => url.includes("/before-missing.png"))).toBe(true);
    expect(urls.some((url) => url.includes("/overall-fit.png"))).toBe(true);
    expect(urls.some((url) => url.includes("/after-imputation.png"))).toBe(true);
    expect(screen.getAllByText(/Nothing has been imputed for this level yet/).length).toBeGreaterThan(0);
    expect(api.runImputation).not.toHaveBeenCalled();
  });

  it("changing a setting redraws the preview and stores nothing", async () => {
    await mount(null);
    setNumber("Random seed", "99");
    setNumber("Quantile", "0.02");
    await waitFor(() => expect(plotUrls().every((url) => url.includes("seed=99"))).toBe(true));
    expect(plotUrls().every((url) => url.includes("qValue=0.02"))).toBe(true);
    expect(api.runImputation).not.toHaveBeenCalled();
  });

  it("the button applies the settings on screen, once", async () => {
    await mount(null);
    setNumber("Random seed", "7");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Impute Data Values" }));
    });
    expect(api.runImputation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.runImputation).mock.calls[0][0]).toMatchObject({ kind: "protein", seed: 7 });
    await waitFor(() => expect(screen.getByText("1234")).toBeTruthy());
  });

  it("the summary and the download describe what is stored, not what is on screen", async () => {
    vi.mocked(api.downloadImputationCsv).mockResolvedValue(new Blob(["x"]));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    await mount(STORED);
    await waitFor(() => expect(screen.getByText("4321")).toBeTruthy());

    setNumber("Random seed", "99");
    expect(screen.getByText("4321")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /download/i }));
    });
    expect(vi.mocked(api.downloadImputationCsv).mock.calls[0][0]).toMatchObject({ seed: 42 });
    expect(api.runImputation).not.toHaveBeenCalled();
  });
});

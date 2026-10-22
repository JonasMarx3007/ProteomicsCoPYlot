/**
 * The phosphoprotein aggregation offers what the API accepts, starting where
 * the API starts.
 *
 * A caller that omits `mode` or `source` gets the API's default; a person who
 * opens the Annotation page gets the page's. If the two drift apart, the same
 * "aggregate" produces a different kind of quantity depending on who asked --
 * `robust_site_median` holds centred ratios, the sums hold abundances. The
 * page's choices are compared with `PhosprotAggregateRequest` in the generated
 * OpenAPI schema (src/lib/generated/openapi.json), and with what it sends.
 *
 * This replaced Python regular expressions over AnnotationPage.tsx
 * (tests/unit/phospho/test_phosprot_aggregation.py).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AnnotationPage from "../../src/features/metadata/AnnotationPage";
import * as api from "../../src/lib/api";
import { DATASETS, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const REQUEST = JSON.parse(readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8"))
  .components.schemas.PhosprotAggregateRequest.properties as Record<string, { default: string; enum: string[] }>;

const PHOSPHO_ANNOTATION = {
  kind: "phospho", sourceRows: 10, sourceColumns: 6, metadataRows: 4, conditionCount: 2, sampleCount: 4,
  metadataPreview: [], log2Rows: 10, log2Columns: 6, filteredRows: 10, filteredColumns: 6, filteredPreview: [],
  isLog2Transformed: true, log2AutoDetected: true, metadataSource: "manual", filter: null, autoDetected: false,
  warnings: [],
  // An applied imputation, so the imputed source is offered too.
  imputation: { mode: "quantile", applied: true, sampleCount: 4 },
} as unknown as Awaited<ReturnType<typeof api.getCurrentAnnotation>>;

beforeEach(async () => {
  silenceNetwork();
  vi.mocked(api.getCurrentDatasets).mockResolvedValue({ ...DATASETS, protein: null });
  vi.mocked(api.getCurrentAnnotation).mockResolvedValue(PHOSPHO_ANNOTATION);
  render(<AnnotationPage />);
  await screen.findByLabelText("Aggregation mode", {}, { timeout: 3000 });
});

const select = (label: string) => screen.getByLabelText(label) as HTMLSelectElement;
const values = (element: HTMLSelectElement) => Array.from(element.options).map((option) => option.value);

describe("the Aggregate to Phosphoprotein card", () => {
  it("offers exactly the modes the API accepts", () => {
    expect(values(select("Aggregation mode")).sort()).toEqual([...REQUEST.mode.enum].sort());
  });

  it("offers exactly the sources the API accepts once an imputed matrix exists", () => {
    expect(values(select("Source data")).sort()).toEqual([...REQUEST.source.enum].sort());
  });

  it("starts on the API's default mode and source", () => {
    expect(select("Aggregation mode").value).toBe(REQUEST.mode.default);
    expect(select("Source data").value).toBe(REQUEST.source.default);
  });

  it("sends the defaults it shows", async () => {
    vi.mocked(api.aggregatePhosprot).mockResolvedValue({} as never);
    fireEvent.click(screen.getByText("Aggregate to Phosphoprotein", { selector: "button" }));
    await waitFor(() => expect(api.aggregatePhosprot).toHaveBeenCalled());
    const [mode, source] = vi.mocked(api.aggregatePhosprot).mock.calls[0];
    expect([mode, source]).toEqual([REQUEST.mode.default, REQUEST.source.default]);
  });
});

describe("the alternative to collapsing: an uploaded phosphoprotein matrix (D17, 2026-10-22)", () => {
  it("is disabled until a file is chosen, then sends the file and the chosen scale", async () => {
    const button = screen.getByText("Use Uploaded Matrix", { selector: "button" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    vi.mocked(api.uploadPhosprotMatrix).mockResolvedValue({} as never);
    const file = new File(["Protein_group,A,B\nP1,1,2\n"], "collapsed.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Phosphoprotein file"), { target: { files: [file] } });
    fireEvent.change(select("Values are"), { target: { value: "log2" } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(api.uploadPhosprotMatrix).toHaveBeenCalled());
    const [sent, scale] = vi.mocked(api.uploadPhosprotMatrix).mock.calls[0];
    expect(sent.name).toBe("collapsed.csv");
    expect(scale).toBe(true);
  });

  it("lets the server detect the scale by default", async () => {
    vi.mocked(api.uploadPhosprotMatrix).mockResolvedValue({} as never);
    const file = new File(["x"], "m.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Phosphoprotein file"), { target: { files: [file] } });
    fireEvent.click(screen.getByText("Use Uploaded Matrix", { selector: "button" }));
    await waitFor(() => expect(api.uploadPhosprotMatrix).toHaveBeenCalled());
    expect(vi.mocked(api.uploadPhosprotMatrix).mock.calls[0][1]).toBeNull();
  });
});

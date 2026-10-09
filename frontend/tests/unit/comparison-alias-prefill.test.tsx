/**
 * Single-sample Venn and Pearson aliases start out as the `WT_1`-style label.
 *
 * The selector keeps the original run names; the alias fields come prefilled
 * with the label every QC plot draws for that sample, follow a new selection,
 * and stay editable. Condition mode leaves the aliases alone.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ComparisonPipelinePage from "../../src/features/comparison/ComparisonPipelinePage";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const RUNS = ["20240822_run_WT_1.d.PG.Quantity", "20240822_run_WT_2.d.PG.Quantity", "20240822_run_GRK_1.d.PG.Quantity"];

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  sessionStorage.clear();
  vi.mocked(api.getComparisonOptions).mockResolvedValue({
    samples: RUNS, conditions: ["WT", "GRK"],
    sampleLabels: { [RUNS[0]]: "WT_1", [RUNS[1]]: "WT_2", [RUNS[2]]: "GRK_1" },
    sampleCount: 3, conditionCount: 2, dataSource: "data", filteredAvailable: false, imputedAvailable: false,
  });
});

it("prefills the Pearson aliases with the plot labels and follows a new selection", async () => {
  render(<ComparisonPipelinePage activeTab="pearson" />);
  const alias1 = (await screen.findByLabelText("Alias 1 (optional)")) as HTMLInputElement;
  const alias2 = screen.getByLabelText("Alias 2 (optional)") as HTMLInputElement;
  await waitFor(() => expect(alias1.value).toBe("WT_1"));
  expect(alias2.value).toBe("WT_2");
  fireEvent.change(screen.getByLabelText("Sample 2"), { target: { value: RUNS[2] } });
  await waitFor(() => expect(alias2.value).toBe("GRK_1"));
  fireEvent.change(alias2, { target: { value: "knockout rep 1" } });
  expect(alias2.value).toBe("knockout rep 1");
});

it("prefills the Venn aliases too and leaves condition mode alone", async () => {
  render(<ComparisonPipelinePage activeTab="venn" />);
  const alias1 = (await screen.findByLabelText("Alias 1 (optional)")) as HTMLInputElement;
  await waitFor(() => expect(alias1.value).toBe("WT_1"));
  expect((screen.getByLabelText("Alias 2 (optional)") as HTMLInputElement).value).toBe("WT_2");
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "Condition" } });
  // Automatic sample labels do not follow into condition mode ("Total A_1"
  // over a condition set); a typed alias would.
  await waitFor(() => expect(alias1.value).toBe(""));
  expect((screen.getByLabelText("Alias 2 (optional)") as HTMLInputElement).value).toBe("");
  fireEvent.change(await screen.findByLabelText("Condition 1"), { target: { value: "GRK" } });
  expect(alias1.value).toBe("");
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "Single" } });
  await waitFor(() => expect(alias1.value).toBe("WT_1")); // refilled on the way back
});

it("keeps a typed alias across a mode change", async () => {
  render(<ComparisonPipelinePage activeTab="pearson" />);
  const alias1 = (await screen.findByLabelText("Alias 1 (optional)")) as HTMLInputElement;
  await waitFor(() => expect(alias1.value).toBe("WT_1"));
  fireEvent.change(alias1, { target: { value: "wild type" } });
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "Condition" } });
  await waitFor(() => expect(screen.getByLabelText("Condition 1")).toBeTruthy());
  expect(alias1.value).toBe("wild type");
  expect((screen.getByLabelText("Alias 2 (optional)") as HTMLInputElement).value).toBe("");
});

it.each(["pearson", "venn"] as const)("replaces stale %s aliases when their samples no longer exist", async (activeTab) => {
  sessionStorage.setItem("pcopylot.ui.comparison.pipeline.v1", JSON.stringify({
    pearson: { mode: "Single", sample1: "old_run", sample2: "other_run", alias1: "Old_1", alias2: "Old_2" },
    venn: { mode: "Single", first: "old_run", second: "other_run", alias1: "Old_1", alias2: "Old_2" },
  }));
  render(<ComparisonPipelinePage activeTab={activeTab} />);
  await waitFor(() => expect((screen.getByLabelText("Alias 1 (optional)") as HTMLInputElement).value).toBe("WT_1"));
  expect((screen.getByLabelText("Alias 2 (optional)") as HTMLInputElement).value).toBe("WT_2");
});

it("keeps a typed Venn alias across a mode change", async () => {
  render(<ComparisonPipelinePage activeTab="venn" />);
  const alias = (await screen.findByLabelText("Alias 1 (optional)")) as HTMLInputElement;
  await waitFor(() => expect(alias.value).toBe("WT_1"));
  fireEvent.change(alias, { target: { value: "wild type" } });
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: "Condition" } });
  await waitFor(() => expect(screen.getByLabelText("Condition 1")).toBeTruthy());
  expect(alias.value).toBe("wild type");
});

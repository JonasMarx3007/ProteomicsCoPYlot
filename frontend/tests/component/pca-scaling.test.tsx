/**
 * The feature-scaling selector names the scaling, and offers each one once.
 *
 * There are two scalings. Centred weights a feature by its variance; unit
 * variance gives every feature equal weight. The selector once offered three
 * entries, "Method default (centred)", "Centred only" and "Unit variance", and
 * for every method one of them was a synonym of another. `auto` still exists in
 * the API and in saved states; it is not something a person can choose.
 *
 * Each method's default is a convention the backend applies too
 * (`resolve_feature_scaling`); both sides are checked against
 * tests/fixtures/pca_default_scaling.json, so they cannot disagree.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import { methodDefaultScaling, scalingLabel, scalingValue, SCALING_LABELS } from "../../src/features/qc/pcaScaling";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "./apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const DEFAULTS: Record<string, string> = JSON.parse(
  readFileSync(resolve(__dirname, "../../../tests/fixtures/pca_default_scaling.json"), "utf-8")
);
const openapi = JSON.parse(
  readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8")
);

function scalingEnum(): string[] {
  const parameters: { name: string; schema: { enum?: string[]; anyOf?: { enum?: string[] }[] } }[] =
    openapi.paths["/api/plots/qc/{kind}/pca.png"].get.parameters;
  const schema = parameters.find((parameter) => parameter.name === "scaling")!.schema;
  return schema.enum ?? schema.anyOf!.find((branch) => branch.enum)!.enum!;
}

describe("the scaling vocabulary", () => {
  it("offers one label per real scaling, and every one the backend takes except auto", () => {
    const offered = SCALING_LABELS.map(scalingValue).sort();
    expect(new Set(offered).size).toBe(SCALING_LABELS.length);
    expect(offered).toEqual(scalingEnum().filter((value) => value !== "auto").sort());
  });

  it("starts each method on the scaling the backend uses for it", () => {
    for (const [method, scaling] of Object.entries(DEFAULTS)) {
      expect(methodDefaultScaling(method), method).toBe(scaling);
    }
  });

  it("shows a saved auto as the scaling it resolves to", () => {
    for (const method of Object.keys(DEFAULTS)) {
      expect(scalingLabel("auto", method)).toBe(scalingLabel(DEFAULTS[method], method));
    }
  });
});

describe("the PCA card", () => {
  function field(label: string): HTMLSelectElement {
    return screen.getByLabelText(label, { selector: "select" }) as HTMLSelectElement;
  }
  const shown = (method: string) => scalingLabel(DEFAULTS[method], method);

  it("lists the two scalings and moves to the new method's default on a switch", async () => {
    silenceNetwork();
    serveDatasets(api);
    vi.mocked(api.getQcPlotOptions).mockResolvedValue({
      conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
      availableDataSources: ["data"], defaultDataSource: "data", centredPhosprotValues: false,
    });
    render(<QCPipelinePage activeTab="pca" />);
    await waitFor(() => expect(screen.getByText("Feature scaling")).toBeTruthy());
    expect(Array.from(field("Feature scaling").options).map((option) => option.text)).toEqual([...SCALING_LABELS]);
    expect(field("Feature scaling").value).toBe(shown("PCA"));

    // A scaling chosen by hand under one method does not follow to the next:
    // the selection moves to the new method's convention.
    fireEvent.change(field("Method"), { target: { value: "UMAP" } });
    expect(field("Feature scaling").value).toBe(shown("UMAP"));
    fireEvent.change(field("Feature scaling"), { target: { value: "Centred" } });
    fireEvent.change(field("Method"), { target: { value: "t-SNE" } });
    expect(field("Feature scaling").value).toBe(shown("t-SNE"));
    fireEvent.change(field("Feature scaling"), { target: { value: "Unit variance" } });
    fireEvent.change(field("Method"), { target: { value: "PCA" } });
    expect(field("Feature scaling").value).toBe(shown("PCA"));
  });
});

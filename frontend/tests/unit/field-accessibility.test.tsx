/**
 * Every label on these pages names the control it sits with.
 *
 * A label is announced with its control when it either points at the control
 * by id (`htmlFor`) or wraps it. A label that does neither is a caption: a
 * screen reader reads the field beside it as unnamed, and `getByLabelText`
 * cannot find it either. These mount each page with a backend that answers its
 * option requests and ask the DOM (`HTMLLabelElement.control`) for every
 * label's control.
 *
 * This replaced regular expressions over the pages' JSX. The parts of that file
 * that were about code shape are ESLint rules now (eslint.config.js,
 * FIELD_RULES): no raw `<input>`, `<select>` or `<textarea>` in the advanced
 * panel, and no raw `<textarea>` in the statistics panels, so every field there
 * registers with the assistant.
 */
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantSurface } from "../../src/components/AssistantFields";
import NumberField from "../../src/components/NumberField";
import CheckboxField from "../../src/components/CheckboxField";
import SelectField from "../../src/components/SelectField";
import CompletenessPage from "../../src/features/completeness/CompletenessPage";
import ColorsPage from "../../src/features/data/ColorsPage";
import IdTranslatorPage from "../../src/features/data/IdTranslatorPage";
import ImputationPage from "../../src/features/data/ImputationPage";
import PeptideLevelPage from "../../src/features/peptide/PeptideLevelPage";
import { PathwayHeatmapPanel } from "../../src/features/stats/PathwayHeatmapPanel";
import { VolcanoPanel } from "../../src/features/stats/VolcanoPanel";
import * as api from "../../src/lib/api";
import { readAssistantControls } from "../../src/lib/assistantControls";
import type { StatisticalOptionsResponse } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const PROTEIN = [{ value: "protein", label: "Protein" }];
const OPTIONS: StatisticalOptionsResponse = {
  kind: "protein", sourceUsed: "data", imputedAvailable: false, availableConditions: ["A", "B"],
  samplesByCondition: { A: ["a1", "a2"], B: ["b1", "b2"] }, pairIdsBySample: {},
  availableIdentifiers: [{ key: "workflow", label: "Protein" }], warnings: [],
  availableDataSources: ["data"], defaultDataSource: "data",
};

const PEPTIDE_OVERVIEW = {
  filename: "peptides.tsv", path: "peptides.tsv", rows: 10, columns: 4, columnNames: ["Sequence", "a1", "b1"],
  availableSamples: ["a1", "b1"], availableProteins: ["P1"], metadataLoaded: true, metadataFilename: "meta.tsv", warnings: [],
} as unknown as Awaited<ReturnType<typeof api.getPeptideOverview>>;

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getStatisticalOptions).mockResolvedValue(OPTIONS);
  vi.mocked(api.getPeptideOverview).mockResolvedValue(PEPTIDE_OVERVIEW);
});

const noop = () => {};
const PAGES: [string, () => ReactElement][] = [
  ["the volcano panel", () => <VolcanoPanel kindOptions={PROTEIN} />],
  ["the pathway heatmap panel", () => <PathwayHeatmapPanel kindOptions={PROTEIN} />],
  ["the Completeness page", () => <CompletenessPage activeTab="missingPlot" />],
  ["the Colors page", () => <ColorsPage />],
  ["the ID Translator page", () => <IdTranslatorPage />],
  ["the Imputation page", () => <ImputationPage />],
  ["the peptide page", () => <PeptideLevelPage activeTab="rtPlot" />],
  ["the shared fields", () => <>
    <SelectField label="Dataset level" value="a" options={["a", "b"]} onChange={noop} />
    <NumberField label="Threshold" value={1} onChange={noop} />
    <CheckboxField label="Show legend" checked onChange={noop} />
  </>],
];

function labels() {
  return Array.from(document.querySelectorAll("label"));
}

describe.each(PAGES)("%s", (_name, element) => {
  it("gives every label a control", async () => {
    render(element());
    // The fields appear once the page has its options.
    await waitFor(() => expect(labels().length).toBeGreaterThan(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    const captions = labels().filter((label) => label.control === null).map((label) => label.textContent?.trim());
    expect(captions).toEqual([]);
  });
});

it("registers the volcano's multi-line field with the assistant as a view control", async () => {
  render(<AssistantSurface module="stats.volcano" enabled><VolcanoPanel kindOptions={PROTEIN} /></AssistantSurface>);
  const field = await screen.findByLabelText("Highlight terms");
  expect(field.tagName).toBe("TEXTAREA");
  const control = readAssistantControls().find((candidate) => candidate.label === "Highlight terms");
  expect(control?.permission).toBe("view");
  expect(control?.type).toBe("text");
});

/**
 * "Show NA as low" on the single-protein line plot is one setting everywhere.
 *
 * The option draws missing values at the bottom of the axis instead of leaving
 * a gap. It has to survive a reload (it is saved with the panel), reach the
 * renderer (it is a parameter of the plot request) and reach the assistant (it
 * is part of the view's context mode), or the figure, the saved state and the
 * explanation can each describe a different plot.
 *
 * This replaced regular expressions over SingleProteinPage.tsx; the page is
 * mounted and the option switched here.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SingleProteinPage from "../../src/features/single-protein/SingleProteinPage";
import * as api from "../../src/lib/api";
import type { ContextMode } from "../../src/lib/types";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getSingleProteinOptions).mockResolvedValue({
    proteins: ["P1"], conditions: ["A", "B"], proteinCount: 1, conditionCount: 2, identifier: "workflow",
    availableIdentifiers: [{ key: "workflow", label: "Protein" }], dataSource: "data",
    availableDataSources: ["data"], defaultDataSource: "data",
  } as Awaited<ReturnType<typeof api.getSingleProteinOptions>>);
});

function lineplotRequests() {
  return vi.mocked(globalThis.fetch).mock.calls.map(([url]) => new URL(String(url), "http://localhost"))
    .filter((url) => url.pathname.endsWith("/lineplot.png"));
}

const saved = () => JSON.parse(sessionStorage.getItem("pcopylot.ui.single.protein.v1") ?? "{}");

async function mount(showNaLow?: boolean) {
  sessionStorage.setItem("pcopylot.ui.single.protein.v1", JSON.stringify({
    line: { proteins: ["P1"], conditions: ["A", "B"], ...(showNaLow === undefined ? {} : { showNaLow }) },
  }));
  const modes: (ContextMode | null)[] = [];
  render(<SingleProteinPage activeTab="lineplot" onContextModeChange={(mode) => modes.push(mode)} />);
  const checkbox = (await screen.findByLabelText("Show NA as low")) as HTMLInputElement;
  await waitFor(() => expect(lineplotRequests().length).toBeGreaterThan(0));
  return { checkbox, modes };
}

describe("Show NA as low", () => {
  it("is off for a panel saved before the option existed", async () => {
    const { checkbox, modes } = await mount();
    expect(checkbox.checked).toBe(false);
    expect(lineplotRequests().at(-1)!.searchParams.get("showNaLow")).toBe("false");
    expect(modes.at(-1)).toMatchObject({ tab: "lineplot", showNaLow: false });
  });

  it("restores a saved choice into the control, the plot request and the assistant's context", async () => {
    const { checkbox, modes } = await mount(true);
    expect(checkbox.checked).toBe(true);
    expect(lineplotRequests().at(-1)!.searchParams.get("showNaLow")).toBe("true");
    expect(modes.at(-1)).toMatchObject({ tab: "lineplot", showNaLow: true });
  });

  it("carries a change to all three and into the saved panel", async () => {
    const { checkbox, modes } = await mount(false);
    fireEvent.click(checkbox);
    await waitFor(() => expect(lineplotRequests().at(-1)!.searchParams.get("showNaLow")).toBe("true"));
    expect(modes.at(-1)).toMatchObject({ showNaLow: true });
    await waitFor(() => expect(saved().line.showNaLow).toBe(true));
  });
});

/**
 * Advanced plot mode decides whether the appearance panel is on screen, and
 * nothing else.
 *
 * It used to decide whether the panel existed: with the panel unmounted its
 * settings were not registered as assistant controls, so a styling request had
 * to turn the mode on first -- the chat said "Enabled advanced plot options."
 * and the user's own switch moved under them (rounds 33-35). The panel is now
 * mounted either way, offscreen and inert while the user keeps it closed, and
 * only the user opens it.
 *
 * These mount the three places that host the panel (App, the QC page and the
 * Completeness page) with the mode off and on. They replaced regular
 * expressions over those files' JSX. How the registry treats the offscreen
 * mount is in assistant-controls.test.tsx; that the assistant has no action
 * that flips the mode is in assistant-sequencing.test.ts, and that its code
 * never calls the setter is an ESLint rule (eslint.config.js, ASSISTANT_RULES).
 */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";
import CompletenessPage from "../../src/features/completeness/CompletenessPage";
import QCPipelinePage from "../../src/features/qc/QCPipelinePage";
import * as api from "../../src/lib/api";
import { getAdvancedPlotMode, setAdvancedPlotMode } from "../../src/lib/appSettings";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const QC_OPTIONS = {
  conditions: ["A", "B"], imputedAvailable: false, samples: ["a1", "b1"],
  availableDataSources: ["data"], defaultDataSource: "data", centredPhosprotValues: false,
} as Awaited<ReturnType<typeof api.getQcPlotOptions>>;

const HOSTS: { name: string; element: () => ReactElement; open?: () => void }[] = [
  { name: "the QC page", element: () => <QCPipelinePage activeTab="coverage" /> },
  { name: "the Completeness page", element: () => <CompletenessPage activeTab="missingPlot" /> },
  {
    name: "App, for the pages without a panel of their own",
    element: () => <App />,
    open: () => fireEvent.click(screen.getByRole("button", { name: "Single Protein" })),
  },
];

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getQcPlotOptions).mockResolvedValue(QC_OPTIONS);
});

async function panel(host: (typeof HOSTS)[number]) {
  render(host.element());
  host.open?.();
  return screen.findByText("Advanced Plot Options", {}, { timeout: 5000 });
}

describe.each(HOSTS)("$name", (host) => {
  it("mounts the appearance panel offscreen while advanced mode is off", async () => {
    setAdvancedPlotMode(false);
    const heading = await panel(host);
    expect(heading.closest('[data-assistant-offscreen="true"]')).not.toBeNull();
    expect(getAdvancedPlotMode()).toBe(false);
  });

  it("shows the same panel on the page once the user turns advanced mode on", async () => {
    setAdvancedPlotMode(true);
    const heading = await panel(host);
    expect(heading.closest("[data-assistant-offscreen]")).toBeNull();
  });
});

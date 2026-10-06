/**
 * The RT plot greys out Mode and Bins while Type is Interactive.
 *
 * `peptide_rt_interactive_html` takes add_line, header, sampling_seed and the
 * figure size. It always draws a scatter and never bins, so Mode and Bins do
 * nothing while Type is Interactive -- a control that silently changes nothing
 * is worse than no control. The gate is a UI change only: both still reach the
 * static renderer.
 *
 * These mount the peptide page and switch Type. They replaced a node --test
 * file that walked the page's syntax tree for each field's `disabled={...}`.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PeptideLevelPage from "../../src/features/peptide/PeptideLevelPage";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

beforeEach(() => {
  silenceNetwork();
  serveDatasets(api);
  vi.mocked(api.getPeptideOverview).mockResolvedValue({
    filename: "peptides.tsv", path: "peptides.tsv", rows: 10, columns: 4, columnNames: ["Sequence", "a1", "b1"],
    availableSamples: ["a1", "b1"], availableProteins: ["P1"], metadataLoaded: true, metadataFilename: "meta.tsv", warnings: [],
  } as unknown as Awaited<ReturnType<typeof api.getPeptideOverview>>);
});

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement;

/** The last RT plot the page asked for. */
function rtRequest() {
  const urls = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url))
    .concat(Array.from(document.querySelectorAll("iframe[src]")).map((frame) => frame.getAttribute("src")!))
    .filter((url) => /\/api\/plots\/peptide\/rt/.test(url));
  return urls.length ? new URL(urls.at(-1)!, "http://localhost") : null;
}

async function mount() {
  render(<PeptideLevelPage activeTab="rtPlot" />);
  await screen.findByLabelText("Mode");
  await waitFor(() => expect(rtRequest()).not.toBeNull());
}

describe("the RT plot options", () => {
  it("leave Mode and Bins usable and send them to the static plot", async () => {
    await mount();
    expect(field("Type").value).toBe("Normal");
    expect(field("Mode").disabled).toBe(false);
    expect(field("Bins").disabled).toBe(false);
    fireEvent.change(field("Mode"), { target: { value: "Hexbin Plot" } });
    await waitFor(() => expect(rtRequest()!.searchParams.get("method")).toBe("Hexbin Plot"));
    expect(rtRequest()!.pathname).toMatch(/\/api\/plots\/peptide\/rt\.png$/);
    expect(rtRequest()!.searchParams.has("bins")).toBe(true);
  });

  it("grey out Mode and Bins once Type is Interactive, and switch to the interactive renderer", async () => {
    await mount();
    fireEvent.change(field("Type"), { target: { value: "Interactive" } });
    await waitFor(() => expect(field("Mode").disabled).toBe(true));
    expect(field("Bins").disabled).toBe(true);
    await waitFor(() => expect(rtRequest()!.pathname).toMatch(/\/api\/plots\/peptide\/rt-interactive\.html$/));
  });

  it("keep Type and Random Seed usable in both types", async () => {
    await mount();
    for (const type of ["Normal", "Interactive"]) {
      fireEvent.change(field("Type"), { target: { value: type } });
      await waitFor(() => expect(field("Type").value).toBe(type));
      expect(field("Type").disabled).toBe(false);
      expect(field("Random Seed").disabled).toBe(false);
    }
  });
});

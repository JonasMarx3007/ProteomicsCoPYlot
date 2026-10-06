/**
 * The notebook export keeps working after its token expires, and says why when it cannot.
 *
 * Exports are kept per session for a while. The button used to stay enabled on
 * an expired one and answer "render the plot again" -- with nothing on the page
 * that would. It now asks the server to draw the same output again for a fresh
 * export and downloads that. A figure the server could not export says why
 * under it, and viewers are offered no notebook (each one carries the data).
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NotebookDownload from "../../src/components/NotebookDownload";
import PlotImage from "../../src/components/PlotImage";

const OLD = "a".repeat(32);
const FRESH = "b".repeat(32);
const PLOT = "/api/plots/qc/protein/boxplot.png?advanced=%7B%7D";

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:zip");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

function serve(answer: (url: string) => Response) {
  const fetch = vi.fn(async (url: string) => answer(String(url)));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const zip = () => new Response("PK", { status: 200,
  headers: { "Content-Disposition": 'attachment; filename="Plot.zip"' } });
const expired = () => new Response(JSON.stringify({ detail: "Notebook snapshot unavailable; render the plot again." }),
  { status: 404, headers: { "content-type": "application/json" } });

describe("an expired export", () => {
  it("is prepared again from the plot on screen and downloaded", async () => {
    const fetch = serve((url) => url.includes(`/notebooks/${OLD}`) ? expired()
      : url.includes(`/notebooks/${FRESH}`) ? zip()
      : new Response("png", { status: 200, headers: { "X-CoPYlot-Notebook": FRESH } }));
    render(<NotebookDownload plotUrl={PLOT} rendered={{ url: PLOT, token: OLD }} />);
    fireEvent.click(screen.getByRole("button", { name: "Export notebook" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining(`/notebooks/${FRESH}.zip`)));
    expect(fetch.mock.calls.map(([url]) => url)).toContain(PLOT);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("of a report asks for the report to be generated again", async () => {
    serve(() => expired());
    render(<NotebookDownload plotUrl="data:text/html,report" outputLabel="report"
      rendered={{ url: "data:text/html,report", token: OLD }} />);
    fireEvent.click(screen.getByRole("button", { name: "Export notebook" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Generate the report again");
  });
});

describe("a figure without an export", () => {
  it("says why under the plot", async () => {
    serve(() => new Response("png", { status: 200, headers: {
      "X-CoPYlot-Notebook-Unavailable": encodeURIComponent("Regenerate annotations after identifier translation before exporting a notebook.") } }));
    render(<PlotImage url={PLOT} alt="plot" />);
    expect(await screen.findByText(
      "Notebook export unavailable: Regenerate annotations after identifier translation before exporting a notebook.")).toBeTruthy();
  });
});

describe("in viewer mode", () => {
  it("no notebook export is offered", async () => {
    vi.resetModules();
    vi.doMock("../../src/lib/appMode", async (original) => ({ ...(await original<object>()), IS_VIEWER_MODE: true }));
    const { default: ViewerNotebookDownload } = await import("../../src/components/NotebookDownload");
    render(<ViewerNotebookDownload plotUrl={PLOT} rendered={{ url: PLOT, token: OLD }} />);
    expect(screen.queryByRole("button", { name: "Export notebook" })).toBeNull();
    vi.doUnmock("../../src/lib/appMode");
  });
});

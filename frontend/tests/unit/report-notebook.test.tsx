/**
 * The report's notebook export belongs to the report it was generated with.
 *
 * A notebook token names one rendered output. The button is enabled only for
 * the output it was captured from, so a notebook can never be exported beside a
 * report it does not reproduce; on the Summary page it sits next to the HTML
 * download and uses the token that came back with that report, and a notebook
 * that could not be built says why.
 *
 * Converted from a node --test file that compiled NotebookDownload.tsx with a
 * fake React, and matched SummaryPage.tsx's JSX with regular expressions; the
 * page is mounted and a report generated here.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NotebookDownload from "../../src/components/NotebookDownload";
import SummaryPage from "../../src/features/summary/SummaryPage";
import * as api from "../../src/lib/api";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const TOKEN = "a".repeat(32);

describe("NotebookDownload", () => {
  it("is enabled only for the captured report", () => {
    const { rerender } = render(<NotebookDownload plotUrl="report-one" outputLabel="report" rendered={{ url: "report-one", token: "snapshot" }} />);
    const button = screen.getByRole("button") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.textContent).toBe("Export notebook");
    expect(button.title).toMatch(/this report/);
    rerender(<NotebookDownload plotUrl="report-one" outputLabel="report" rendered={{ url: "report-two", token: "snapshot" }} />);
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    rerender(<NotebookDownload plotUrl="report-one" outputLabel="report" rendered={{ url: "report-one", token: null }} />);
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("the Summary report", () => {
  beforeEach(() => {
    silenceNetwork();
    serveDatasets(api);
  });

  async function generate(response: Partial<Awaited<ReturnType<typeof api.generateSummaryReport>>>) {
    vi.mocked(api.generateSummaryReport).mockResolvedValue({ fileName: "report.html", html: "<html>Report</html>", warnings: [], ...response });
    render(<SummaryPage activeTab="report" />);
    fireEvent.click(screen.getByText("Generate HTML Report"));
    return screen.findByText("Download HTML Report");
  }

  it("puts the notebook export next to the HTML download, armed with the report's own token", async () => {
    const download = await generate({ notebookToken: TOKEN });
    const notebook = download.nextElementSibling as HTMLButtonElement;
    expect(notebook.textContent).toBe("Export notebook");
    expect(notebook.disabled).toBe(false);
    expect(notebook.title).toMatch(/this report/);
    vi.mocked(globalThis.fetch).mockClear();
    fireEvent.click(notebook);
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(String(vi.mocked(globalThis.fetch).mock.calls[0][0])).toContain(`/api/plots/notebooks/${TOKEN}.zip`);
  });

  it("disables the export and says why when the report came without a notebook", async () => {
    const download = await generate({ notebookToken: null, notebookError: "The notebook could not be built for this report." });
    expect((download.nextElementSibling as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toBe("The notebook could not be built for this report.");
  });
});

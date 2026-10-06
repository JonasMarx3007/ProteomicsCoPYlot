/**
 * A refused plot is replaced by its explanation, not shown as a broken image.
 *
 * Every page that shows a rendered plot had its own copy of the same handler,
 * and every copy left the <img> on the page after the request failed -- so the
 * browser's broken-image icon sat above the explanation. A refusal such as "no
 * matching pathway genes were found in the current dataset" is the answer, and
 * it has to replace the figure rather than accompany a broken one. PlotImage is
 * the one implementation now.
 *
 * These mount PlotImage against a backend that refuses or answers. They replaced
 * index arithmetic over PlotImage.tsx's source; that no page renders a plot
 * <img> or keeps a private error handler is an ESLint rule (eslint.config.js,
 * GLOBAL_RULES).
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PlotImage from "../../src/components/PlotImage";
import { PLOT_ERROR_FALLBACK, plotErrorMessage } from "../../src/lib/plotError";

const created: string[] = [];
const revoked: string[] = [];

beforeEach(() => {
  created.length = 0;
  revoked.length = 0;
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => { created.push(`blob:plot-${created.length}`); return created.at(-1)!; });
  URL.revokeObjectURL = vi.fn((url: string) => { revoked.push(url); });
});
afterEach(() => vi.unstubAllGlobals());

function serve(answer: (url: string) => Response) {
  const fetch = vi.fn(async (url: string, options?: RequestInit) => { void options; return answer(url); });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("PlotImage", () => {
  it("replaces the image with the reason the backend gave for refusing it", async () => {
    serve(() => new Response(JSON.stringify({ detail: "No matching pathway genes were found in the current dataset." }), { status: 422 }));
    const { container } = render(<PlotImage url="/api/plots/pathway.png" alt="Pathway heatmap" />);
    expect(await screen.findByText("No matching pathway genes were found in the current dataset.")).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the fallback, not the body, when a refusal carries no readable message", async () => {
    serve(() => new Response("<html>Bad gateway</html>", { status: 502 }));
    const { container } = render(<PlotImage url="/api/plots/pathway.png" alt="Pathway heatmap" />);
    expect(await screen.findByText(PLOT_ERROR_FALLBACK)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the figure once, from one request with the page's URL", async () => {
    const fetch = serve(() => new Response("png", { headers: { "X-CoPYlot-Notice": "Ten%20rows%20dropped" } }));
    render(<PlotImage url="/api/plots/qc.png?dpi=300" alt="QC plot" />);
    const image = await screen.findByAltText("QC plot");
    expect(image.getAttribute("src")).toBe("blob:plot-0");
    expect(screen.getByText("Ten rows dropped")).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/plots/qc.png?dpi=300");
  });

  it("tries again for a new URL, cancelling the old request and releasing the old image", async () => {
    const fetch = serve((url) => url.includes("bad")
      ? new Response(JSON.stringify({ detail: "Select a condition" }), { status: 422 })
      : new Response("png"));
    const { rerender } = render(<PlotImage url="/api/plots/bad.png" alt="Plot" />);
    expect(await screen.findByText("Select a condition")).toBeTruthy();

    // Changing a control changes the URL: the error is not carried over.
    rerender(<PlotImage url="/api/plots/good.png?a=1" alt="Plot" />);
    expect((await screen.findByAltText("Plot")).getAttribute("src")).toBe("blob:plot-0");
    expect(screen.queryByText("Select a condition")).toBeNull();

    rerender(<PlotImage url="/api/plots/good.png?a=2" alt="Plot" />);
    await waitFor(() => expect(screen.getByAltText("Plot").getAttribute("src")).toBe("blob:plot-1"));
    expect(revoked).toEqual(["blob:plot-0"]);
    const signals = fetch.mock.calls.map(([, options]) => options!.signal!);
    expect(signals.length).toBe(3);
    expect(signals.slice(0, 2).every((signal) => signal.aborted)).toBe(true);
    expect(signals[2].aborted).toBe(false);
  });
});

describe("plotErrorMessage", () => {
  it("exposes only readable messages, never the input or arbitrary objects", () => {
    expect(plotErrorMessage({ detail: "No matching features" })).toBe("No matching features");
    expect(plotErrorMessage({ detail: [{ msg: "Width must be positive", input: "private input" }, { msg: "Select a condition" }] }))
      .toBe("Width must be positive; Select a condition");
    expect(plotErrorMessage({ detail: { msg: "Invalid selection", input: "private input" } })).toBe("Invalid selection");
    expect(plotErrorMessage({ detail: [" repeated ", { msg: "repeated" }] })).toBe("repeated");
    for (const payload of [null, [], "error", {}, { detail: {} }, { detail: [{ msg: {} }] }, { detail: "  " }]) {
      expect(plotErrorMessage(payload)).toBe(PLOT_ERROR_FALLBACK);
    }
  });
});

/**
 * Generated plot HTML runs in a sandbox without same-origin privileges.
 *
 * An interactive plot is HTML the backend generated from uploaded data: sample
 * names, protein descriptions, GO terms. In a frame with `allow-same-origin` a
 * script in it could read the session's cookies and storage, so the frames that
 * show it allow scripts (Plotly) and downloads (its camera button) and nothing
 * else. These mount the two shared frames and read the attribute the browser
 * enforces.
 *
 * This replaced a scan of every feature .tsx file for `<iframe` tags; that every
 * frame in src/features carries the same sandbox is now an ESLint rule
 * (eslint.config.js, FRAME_RULES).
 */
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InteractivePlot from "../../src/components/InteractivePlot";
import { PlotFrame } from "../../src/features/stats/statsShared";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

afterEach(() => vi.unstubAllGlobals());

function sandboxOf(frame: HTMLIFrameElement | null) {
  expect(frame, "no frame was rendered").not.toBeNull();
  return (frame!.getAttribute("sandbox") ?? "").split(/\s+/).filter(Boolean).sort();
}

describe("plot frames", () => {
  it("run the shared interactive plot with scripts and downloads only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html><head></head><body>plot</body></html>")));
    const { container } = render(<InteractivePlot url="/api/plots/x.html" title="Plot" height={400} onRendered={() => {}} />);
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    expect(sandboxOf(container.querySelector("iframe"))).toEqual(["allow-downloads", "allow-scripts"]);
  });

  it("keeps the readiness nonce out of executable code and rejects forged messages", async () => {
    const token = "a".repeat(32);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html><head></head><body>plot</body></html>", {
      headers: { "X-CoPYlot-Notebook": token },
    })));
    const onRendered = vi.fn();
    const { container } = render(<InteractivePlot url="/api/plots/x.html" title="Plot" height={400} onRendered={onRendered} />);
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    const frame = container.querySelector("iframe")!;
    const doc = new DOMParser().parseFromString(frame.srcdoc, "text/html");
    const bridge = doc.querySelector<HTMLScriptElement>("script[data-copylot-ready]")!;
    const nonce = bridge.dataset.copylotReady!;
    await act(async () => {});
    expect(nonce).toMatch(/^[a-f0-9]{32}$/);
    expect(bridge.textContent).not.toContain(nonce);
    for (const [source, value] of [[window, nonce], [frame.contentWindow, "wrong"]] as const) {
      window.dispatchEvent(new MessageEvent("message", { source, data: { type: "copylot-plot-ready", nonce: value } }));
    }
    expect(onRendered).not.toHaveBeenCalled();
    await waitFor(() => {
      window.dispatchEvent(new MessageEvent("message", {
        source: frame.contentWindow, data: { type: "copylot-plot-ready", nonce },
      }));
      expect(onRendered).toHaveBeenCalledWith("/api/plots/x.html", token);
    });
  });

  it("run a statistics plot frame with scripts and downloads only", () => {
    const { container } = render(<PlotFrame title="Volcano" url="/api/plots/volcano.html" height={400} />);
    expect(sandboxOf(container.querySelector("iframe"))).toEqual(["allow-downloads", "allow-scripts"]);
  });
});

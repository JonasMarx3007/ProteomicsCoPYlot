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
import { render, waitFor } from "@testing-library/react";
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

  it("run a statistics plot frame with scripts and downloads only", () => {
    const { container } = render(<PlotFrame title="Volcano" url="/api/plots/volcano.html" height={400} />);
    expect(sandboxOf(container.querySelector("iframe"))).toEqual(["allow-downloads", "allow-scripts"]);
  });
});

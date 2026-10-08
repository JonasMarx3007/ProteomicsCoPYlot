// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { PLOTLY_MARKER, withSharedPlotly } from "../../src/lib/sharedPlotly";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.resetModules();
});

function page(asset: string | null) {
  return new Response("", { headers: asset ? { "X-CoPYlot-Plotly-Asset": asset } : {} });
}

describe("shared plotly.js", () => {
  it.each(["", "/dev", "/dev/", "https://backend.example", "https://backend.example/dev/"])(
    "uses the configured API address and tab session for %j", async (base) => {
      vi.stubEnv("VITE_API_BASE_URL", base);
      vi.resetModules();
      const { withSharedPlotly: hydrate } = await import("../../src/lib/sharedPlotly");
      const { TAB_API_PREFIX } = await import("../../src/lib/tabSession");
      const fetched = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("window.Plotly={};"));
      await hydrate(`<script>${PLOTLY_MARKER}</script>`, page("/api/runtime/plotly-7.1.0.js"));
      expect(fetched).toHaveBeenCalledWith(`${base.replace(/\/+$/, "")}${TAB_API_PREFIX}/api/runtime/plotly-7.1.0.js`);
    },
  );

  it("puts the library back inline, fetched once per version", async () => {
    const source = "window.Plotly={$&:1,'$1':2};";
    const fetched = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(source));
    const html = `<head><script>${PLOTLY_MARKER}</script></head>`;
    const first = await withSharedPlotly(html, page("/api/runtime/plotly-7.1.0.js"));
    const second = await withSharedPlotly(html, page("/api/runtime/plotly-7.1.0.js"));
    expect(first).toBe(`<head><script>${source}</script></head>`);
    expect(second).toBe(first);
    expect(fetched).toHaveBeenCalledTimes(1);
  });

  it("leaves a self-contained page alone and ignores foreign asset paths", async () => {
    const fetched = vi.spyOn(globalThis, "fetch");
    expect(await withSharedPlotly("<p>inline</p>", page("/api/runtime/plotly-7.1.0.js"))).toBe("<p>inline</p>");
    const marked = `<script>${PLOTLY_MARKER}</script>`;
    expect(await withSharedPlotly(marked, page("https://evil.example/x.js"))).toBe(marked);
    expect(fetched).not.toHaveBeenCalled();
  });
});

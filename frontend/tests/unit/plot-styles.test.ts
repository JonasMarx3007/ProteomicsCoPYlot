/**
 * Named plot styles and "this style on every plot" (lib/plotStyles.ts), and
 * the pipeline fence in the browser (lib/assistantControls.ts).
 */
import { beforeEach, describe, expect, it } from "vitest";
import { applyStyle, registerStyleStore, saveStyle, savedStyleNames, styleOf, styleTemplate, withStyle } from "../../src/lib/plotStyles";
import { isPipelineControl } from "../../src/lib/assistantControls";
import type { AdvancedPlotSettings } from "../../src/lib/types";

beforeEach(() => window.sessionStorage.clear());

function store(initial: Record<string, AdvancedPlotSettings>, active: string) {
  const state = { byKey: { ...initial }, active };
  const unregister = registerStyleStore("test", {
    active: () => state.byKey[state.active] ?? {},
    setActive: (settings) => { state.byKey[state.active] = settings; },
    setAll: (style) => {
      state.byKey = Object.fromEntries(Object.entries(state.byKey).map(([key, value]) => [key, withStyle(value, style)]));
      return Object.keys(state.byKey).length;
    },
  });
  return { state, unregister };
}

describe("plot styles", () => {
  it("carry the look without a plot's own words", () => {
    const style = styleOf({ fontFamily: "helvetica", titleElement: { text: "Coverage", size: 9 }, legendTitle: "Groups" });
    expect(style).toEqual({ fontFamily: "helvetica", titleElement: { size: 9 } });
    expect(withStyle({ titleElement: { text: "Volcano", size: 14 }, legendTitle: "Sig." }, style))
      .toEqual({ fontFamily: "helvetica", titleElement: { size: 9, text: "Volcano" }, legendTitle: "Sig." });
  });

  it("are saved by name and applied to this plot or every plot", () => {
    const { state, unregister } = store({ a: { fontFamily: "helvetica", xTickLabelSize: 7, titleElement: { text: "A" } },
      b: { fontFamily: "times", titleElement: { text: "B" } } }, "a");
    expect(saveStyle("lab")).toContain('"lab"');
    expect(savedStyleNames()).toEqual(["lab"]);
    state.active = "b";
    applyStyle("lab", "this");
    expect(state.byKey.b).toMatchObject({ fontFamily: "helvetica", xTickLabelSize: 7, titleElement: { text: "B" } });
    state.byKey.b = { fontFamily: "times" };
    expect(applyStyle("lab", "all")).toContain("2 plots");
    expect(state.byKey.b.fontFamily).toBe("helvetica");
    expect(styleTemplate()).toMatchObject({ fontFamily: "helvetica" });
    unregister();
  });

  it("reach a page that was closed when they were applied to all plots", () => {
    const first = store({ a: { fontFamily: "helvetica" } }, "a");
    applyStyle("", "all");
    first.unregister();
    const later = { byKey: { q: { fontFamily: "times" } as AdvancedPlotSettings } };
    const unregister = registerStyleStore("qc", {
      active: () => null, setActive: () => {},
      setAll: (style) => { later.byKey = { q: withStyle(later.byKey.q, style) }; return 1; },
    });
    expect(later.byKey.q.fontFamily).toBe("helvetica");
    unregister();
  });
});

describe("the pipeline fence", () => {
  it.each(["Localization probability cutoff", "Normalization", "Imputation method", "Filter *_M1", "Minimum valid values"])(
    "%s is never an assistant control", (label) => expect(isPipelineControl(label)).toBe(true));
  it.each(["Data Source", "Dataset level", "Title / Size", "Condition 1"])(
    "%s stays available", (label) => expect(isPipelineControl(label)).toBe(false));
});

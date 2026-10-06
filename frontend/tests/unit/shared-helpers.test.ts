/**
 * Small shared helpers that many pages rely on to agree with each other.
 *
 * One data-source resolver, one plot-setting serialiser, one CSV writer, one
 * list of download formats, one context-mode store, one snapshot of the tab's
 * session storage, and the canvas's saved-state migrations. Each was once
 * written out per page, and each copy drifted.
 *
 * Converted from a node --test file that transpiled the modules by hand and cut
 * two helpers out of AnalysisPage.tsx as text; those helpers now live in
 * features/analysis/canvasState.ts. The assistant-registry checks that were here
 * moved to assistant-controls.test.tsx, and the control test types to
 * statisticalTests.test.ts.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { canvasPointStyle, restoredOraState, restoredVolcanoStyle } from "../../src/features/analysis/canvasState";
import { assistantStep } from "../../src/lib/api";
import { activeContextSlot, CONTEXT_SLOTS, contextText, keepOnly, withContextMode } from "../../src/lib/contextModes";
import { resolveSelectedLocalPath } from "../../src/lib/localFilePath";
import { coercePlotDownloadFormat, PLOT_DOWNLOAD_FORMAT_OPTIONS, withPlotDownloadFilename, withPlotDownloadFormat } from "../../src/lib/plotDownload";
import { compactAdvancedPlotSettings, compactMap, compactTextElement } from "../../src/lib/plotSerialization";
import { getSummaryReportContext, saveQcReportSettings } from "../../src/lib/reportState";
import { applyCopylotSessionStorageState, captureCopylotSessionStorageState, clearCopylotClientStorageState } from "../../src/lib/restoreUiState";
import { collectColumns, formatCellValue, rowsToCsv, rowsToQuotedCsv } from "../../src/lib/tableData";
import { dataSourceOptions, resolveDataSource } from "../../src/lib/types";

afterEach(() => vi.unstubAllGlobals());

describe("the data-source resolver", () => {
  it("keeps the source on empty filtering and does not hide it after an options error", () => {
    const choices = { availableDataSources: ["data", "filtered"], defaultDataSource: "filtered" } as const;
    expect(resolveDataSource("filtered", choices as never)).toBe("filtered");
    expect(resolveDataSource(null, choices as never)).toBe("filtered");
    expect(resolveDataSource("data", choices as never)).toBe("data");
    expect(dataSourceOptions(null, "filtered").some((option) => option.value === "filtered")).toBe(true);
  });
});

describe("plot setting serialisation", () => {
  it("keeps QC box and correlation styles intact", () => {
    const styles = { boxBorderColor: "#123456", boxMedianColor: "#654321", boxOutlierColor: "#abcdef",
      boxOutlierEdgeColor: "#fedcba", boxOutlierSize: 7, correlationColorMap: "viridis" };
    expect(compactAdvancedPlotSettings(styles as never)).toEqual(styles);
  });

  it("keeps signed offsets and explicit styling of a text element without mutating it", () => {
    const value = Object.freeze({ text: " Title ", size: 12, xOffset: -2, yOffset: 3, bold: true, italic: true });
    expect(compactTextElement(value)).toEqual({ text: "Title", size: 12, xOffset: -2, yOffset: 3, bold: true, italic: true });
    expect(compactTextElement(undefined)).toBeUndefined();
    expect(compactTextElement({ text: " ", size: 0, xOffset: 0, yOffset: 0, bold: false })).toBeUndefined();
  });

  it("trims maps, omits blank entries and keeps the last-key-wins rule", () => {
    expect(compactMap({ " a ": " first ", a: "last", b: " ", " ": "x" })).toEqual({ a: "last" });
    expect(compactMap(undefined)).toBeUndefined();
  });
});

describe("tables", () => {
  it("escape CSV headers and keep every row without rounding", () => {
    const columns = ["sample,1", 'say "hi"', "line\nbreak", "carriage\rreturn", "number"];
    const rows = Array.from({ length: 205 }, (_, i) => ({
      "sample,1": `P${i}`, 'say "hi"': 'a"b', "line\nbreak": "x\ny", "carriage\rreturn": "x\ry", number: 0.12345678901234568,
    }));
    const header = '"sample,1","say ""hi""","line\nbreak","carriage\rreturn"';
    expect(rowsToCsv(rows, columns)).toBe(header + ",number\n" + rows.map((_, i) =>
      `P${i},"a""b","x\ny","x\ry",0.12345678901234568`).join("\n"));
    expect(rowsToQuotedCsv(rows, columns)).toBe(header + ',"number"\n' + rows.map((_, i) =>
      `"P${i}","a""b","x\ny","x\ry","0.12345678901234568"`).join("\n"));
  });

  it("keep the first-seen column order across heterogeneous rows without mutation", () => {
    const rows = Object.freeze([Object.freeze({ b: 1, a: 2 }), Object.freeze({ c: 3, b: 4 })]);
    expect(collectColumns(rows as never)).toEqual(["b", "a", "c"]);
    expect(collectColumns([])).toEqual([]);
  });

  it("keep the preview's rounding and its non-numeric representation", () => {
    expect([null, undefined, 0, 1.234567, true, false, { a: 1 }, "text"].map(formatCellValue))
      .toEqual(["", "", "0", "1.2346", "true", "false", '{"a":1}', "text"]);
  });

  it("keep precision, missing cells, escaping and the empty behaviour in both CSV variants", () => {
    const rows = [{ n: 0.12345678901234568, text: 'a,"b"\nc', empty: null }];
    const columns = ["n", "text", "empty", "missing"];
    expect(rowsToCsv(rows, columns)).toBe('n,text,empty,missing\n0.12345678901234568,"a,""b""\nc",,');
    expect(rowsToQuotedCsv(rows, columns)).toBe('"n","text","empty","missing"\n"0.12345678901234568","a,""b""\nc","",""');
    expect(rowsToCsv([], ["n"])).toBe("n");
    expect(rowsToQuotedCsv([], ["n"])).toBe("");
    expect(rowsToQuotedCsv(rows, [])).toBe("");
  });
});

describe("local file paths", () => {
  it("share native-path precedence between upload and restore and reject browser fake paths", () => {
    expect(resolveSelectedLocalPath({ path: " C:/data/a.tsv " }, "C:/other.tsv")).toBe("C:/data/a.tsv");
    expect(resolveSelectedLocalPath({}, " C:/data/a.tsv ")).toBe("C:/data/a.tsv");
    expect(resolveSelectedLocalPath({}, "C:\\FAKEPATH\\a.tsv")).toBeNull();
    expect(resolveSelectedLocalPath({ path: " " }, "")).toBeNull();
  });
});

// Every page used to keep its own list of download formats, so a format the
// backend accepted could still be dropped when a page restored its saved state.
describe("download formats", () => {
  it("are one list that a page offers, remembers and names files by", () => {
    const offered = PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => option.value);
    expect(offered).toEqual(["png", "jpg", "webp", "pdf", "svg"]);
    for (const format of offered) {
      expect(coercePlotDownloadFormat(format)).toBe(format);
      expect(withPlotDownloadFilename("qc_cv_protein.png", format)).toBe(`qc_cv_protein.${format}`);
    }
    // PNG is what the route already returns, so it asks for nothing.
    expect(withPlotDownloadFormat("/api/plots/qc/protein/cv.png", "png")).toBe("/api/plots/qc/protein/cv.png");
    expect(withPlotDownloadFormat("/api/plots/qc/protein/cv.png?dpi=300", "svg")).toBe("/api/plots/qc/protein/cv.png?dpi=300&downloadFormat=svg");
    // A saved state from an older build, or a hand-edited one.
    expect(coercePlotDownloadFormat("tiff")).toBe("png");
    expect(coercePlotDownloadFormat(undefined)).toBe("png");
    expect(coercePlotDownloadFormat(" SVG ")).toBe("svg");
    // An .svg name is replaced, not appended to.
    expect(withPlotDownloadFilename("plot.svg", "pdf")).toBe("plot.pdf");
  });
});

describe("context modes", () => {
  it("carry names with delimiters and arrays as they are", () => {
    // The string grammars had to escape `|`, `=` and `,`; an object has nothing to escape.
    const names = ["P1;P2", "Drug, high", "A|B=δ", "100% ready", 'quote"name'];
    const mode = { protein: names[2], proteins: names, conditions: names, header: false };
    expect(JSON.parse(JSON.stringify(mode))).toEqual(mode);
    const query = new URLSearchParams({ proteins: JSON.stringify(names) });
    expect(JSON.parse(new URLSearchParams(query.toString()).get("proteins")!)).toEqual(names);
  });

  it("are read for the view on screen", () => {
    const nav = { section: "", dataTab: "", qcTab: "", statsTab: "", completenessTab: "", peptideTab: "",
      singleProteinTab: "", comparisonTab: "", phosphoTab: "" };
    const at = (overrides: Partial<typeof nav>) => activeContextSlot({ ...nav, ...overrides } as never);
    expect(at({ section: "stats", statsTab: "anova" })).toBe("stats:anova");
    expect(at({ section: "qc", qcTab: "pca" })).toBe("qc:pca");
    expect(at({ section: "qc", qcTab: "histogram" })).toBeNull();
    expect(at({ section: "phospho", phosphoTab: "ksea" })).toBe("phospho:ksea");
    expect(at({ section: "phospho", phosphoTab: "sty" })).toBe("phospho");
    expect(at({ section: "singleProtein", singleProteinTab: "heatmap" })).toBe("singleProtein");
    expect(at({ section: "peptide", peptideTab: "unknown" })).toBeNull();
    expect(at({ section: "data", dataTab: "upload" })).toBeNull();
    expect(at({ section: "analysis" })).toBe("analysis");
    // Every slot a view can resolve to is one App hands a reporter for.
    for (const tab of ["volcano", "anova", "ora", "pathwayHeatmap", "simulation"]) {
      expect(CONTEXT_SLOTS, tab).toContain(at({ section: "stats", statsTab: tab }));
    }
  });

  it("change the store only when a view reports something new", () => {
    const empty = {};
    const one = withContextMode(empty, "stats:volcano", { type: "Normal", kind: "protein" });
    expect(one).toEqual({ "stats:volcano": { type: "Normal", kind: "protein" } });
    // The same selections again, as a new object: no new store, so no re-render.
    expect(withContextMode(one, "stats:volcano", { type: "Normal", kind: "protein" })).toBe(one);
    expect(withContextMode(one, "stats:volcano", { type: "Interactive", kind: "protein" })).not.toBe(one);
    // null withdraws the view's entry; withdrawing nothing is no change.
    expect(withContextMode(one, "stats:volcano", null)).toEqual({});
    expect(withContextMode(empty, "qc:pca", null)).toBe(empty);
    // Leaving a view drops every other view's selections.
    const two = withContextMode(one, "qc:pca", { method: "PCA" });
    expect(keepOnly(two, "qc:pca")).toEqual({ "qc:pca": { method: "PCA" } });
    expect(keepOnly(two, null)).toEqual({});
    expect(keepOnly(one, "stats:volcano")).toBe(one);
    // Values are read as typed; text comparisons are case-insensitive.
    expect(contextText({ type: "Normal" }, "type")).toBe("normal");
    expect(contextText({ type: true }, "type")).toBe("");
    expect(contextText(null, "type")).toBe("");
  });
});

describe("the assistant request", () => {
  it("passes cancellation through to fetch", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn(async (_url: string, options: RequestInit) => {
      expect(options.signal).toBe(controller.signal);
      throw new DOMException("Stopped", "AbortError");
    }));
    await expect(assistantStep({ message: "hello", view: {} as never, receipts: [] }, controller.signal))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("the report context", () => {
  it("keeps peptide coverage beside the module settings and the missingness choices", () => {
    saveQcReportSettings("peptide", { coverage: { quantityColumn: "LFQ intensity" } });
    saveQcReportSettings("peptide", { rtPlot: { method: "Scatter" } });
    const missingPlot = { quantityColumn: "LFQ intensity", binCount: 2, header: false, widthCm: 25 };
    sessionStorage.setItem("pcopylot.ui.completeness.v1", JSON.stringify({ missingPlot }));
    const context = getSummaryReportContext();
    expect(context.qcSettings.peptide).toEqual({ coverage: { quantityColumn: "LFQ intensity" }, rtPlot: { method: "Scatter" } });
    expect(context.completenessSettings).toEqual(missingPlot);
  });
});

describe("the tab's analysis snapshot", () => {
  it("stays tab-local and leaves out the tab routing ID", () => {
    sessionStorage.setItem("copylot.tab.id", "a".repeat(32));
    sessionStorage.setItem("pcopylot.report.qcSettings.v1", '{"title":"Only this tab"}');
    sessionStorage.setItem("unrelated", "keep");
    expect(captureCopylotSessionStorageState()).toEqual({ "pcopylot.report.qcSettings.v1": '{"title":"Only this tab"}' });
    applyCopylotSessionStorageState({ "copylot.tab.id": "foreign", "pcopylot.ui.plot": "restored" });
    expect(sessionStorage.getItem("copylot.tab.id")).toBe("a".repeat(32));
    expect(sessionStorage.getItem("pcopylot.ui.plot")).toBe("restored");
    clearCopylotClientStorageState();
    expect(Object.keys(sessionStorage).sort()).toEqual(["copylot.tab.id", "unrelated"]);
    expect(sessionStorage.getItem("copylot.tab.id")).toBe("a".repeat(32));
  });
});

describe("the canvas's saved state", () => {
  it("separates the editable ORA inputs from a completed result and rejects a broken snapshot", () => {
    const completed = {
      inputSource: "list", namedList: "original",
      request: { genes: ["G1"], backgroundGenes: [], backgroundMode: "global", topN: 10, minTermSize: 20, maxTermSize: 300, adjPValueCutoff: .05 },
      result: { genes: ["G1"], backgroundGenes: [], backgroundMode: "global", warnings: [], organism: "human", correctionMethod: "BH", databaseSha256: "synthetic",
        backgroundSize: 100, annotatedBackgroundSize: 100, testedTermCount: 1, evidenceToken: "saved-token",
        termCounts: { query: { searchSpace: 1, overlapTested: 1, passingCutoff: 1, displayed: 1 } },
        terms: [{ source: "GO", termId: "T", name: "term", termSize: 20, intersectionSize: 1, querySize: 1, geneRatio: 1, hitPercent: 5, pValue: .01, adjPValue: .01, intersectingGenes: ["G1"] }] },
    };
    const restored = restoredOraState({ sourceMode: "manual", genesText: "G2", adjPValueCutoff: .5, completed });
    expect(restored.genesText).toBe("G2");
    expect(restored.adjPValueCutoff).toBe(.5);
    expect(restored.completed).toEqual(completed);
    expect(restoredOraState(null).completed).toBeNull();
    expect(restoredOraState({ genesText: "G2", completed: {} }).genesText).toBe("G2");
    for (const damage of [
      (value: typeof completed) => { (value.result.terms[0] as Record<string, unknown>).adjPValue = "invalid"; },
      (value: typeof completed) => { (value.result as Record<string, unknown>).termCounts = null; },
      (value: typeof completed) => { (value.result as Record<string, unknown>).warnings = {}; },
      (value: typeof completed) => { (value as Record<string, unknown>).request = null; },
    ]) {
      const malformed = structuredClone(completed);
      damage(malformed);
      expect(restoredOraState({ completed: malformed }).completed).toBeNull();
    }
    const empty = structuredClone(completed);
    empty.result.terms = [];
    expect(restoredOraState({ completed: empty }).completed).toEqual(empty);
  });

  it("migrates a saved canvas volcano style into the shared settings", () => {
    // The tile used to hold its own five-field style: two colours, a radius and
    // an opacity. The saved SVG *radius* becomes the shared *diameter*, which is
    // what every size in this tool means, and a saved colour is kept only if it
    // is one.
    const defaults = restoredVolcanoStyle(null);
    expect(defaults.volcanoUpSize, "the 2.8 default radius is a 5.6 diameter").toBe(5.6);
    expect(canvasPointStyle(defaults, "Upregulated").radius, "and draws at the old radius").toBe(2.8);
    expect(restoredVolcanoStyle({ radius: Infinity }).volcanoUpSize).toBe(5.6);
    expect(restoredVolcanoStyle({ radius: -5 }).volcanoUpSize, "clamped to a radius of 1").toBe(2);
    expect(restoredVolcanoStyle({ radius: 100 }).volcanoUpSize, "clamped to a radius of 10").toBe(20);

    expect(restoredVolcanoStyle({ up: "url(https://example.invalid/image)" }).volcanoUpColor).toBe(defaults.volcanoUpColor);
    expect(restoredVolcanoStyle({ up: "#abcdef" }).volcanoUpColor).toBe("#abcdef");
    expect(restoredVolcanoStyle({ title: { bad: true } }).titleElement).toBeUndefined();
    expect(restoredVolcanoStyle({ title: "A & B <test>" }).titleElement).toEqual({ text: "A & B <test>" });

    // A canvas already on the shared shape is handed back untouched, so the
    // migration cannot run twice and halve or double a size.
    const shared = { volcanoUpSize: 9, volcanoUpColor: "#111111" };
    expect(restoredVolcanoStyle(shared)).toBe(shared);

    // Every class resolves, and an out-of-range opacity is brought into [0, 1].
    for (const significance of ["Upregulated", "Downregulated", "Not significant"]) {
      const point = canvasPointStyle({ volcanoUpAlpha: 5, volcanoNsAlpha: -1 }, significance);
      expect(point.radius).toBeGreaterThan(0);
      expect(point.opacity >= 0 && point.opacity <= 1).toBe(true);
      expect(point.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});

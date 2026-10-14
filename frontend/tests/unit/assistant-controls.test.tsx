/**
 * The registry of controls the assistant may read and change.
 *
 * A form control on an assistant surface registers itself; the assistant reads
 * what is registered, never the page source. These tests mount real controls
 * and check what the registry reports: labels carry every enclosing group, a
 * plot's size row is a bounded cosmetic control while other numbers need
 * approval, a hidden control is not readable (except inside the offscreen
 * appearance mount, which only the user's own switch shows), option searches
 * read the displayed names, and canvas additions are verified tile by tile.
 *
 * Replaced node --test checks that cut functions out of assistantControls.ts,
 * PlotFields.tsx and AssistantFields.tsx as text and ran them on fake nodes, and
 * regular expressions over the mount's JSX.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { AssistantAppearanceMount, AssistantCanvasButton, AssistantInput, AssistantSelect, AssistantSurface } from "../../src/components/AssistantFields";
import NumberField from "../../src/components/NumberField";
import { SizeRow } from "../../src/components/PlotFields";
import {
  addCanvasTiles,
  applyAssistantControls,
  assistantFeatureChoices,
  assistantSurfaceReady,
  assistantChanges,
  beginAssistantRequest,
  isGroupedSetting,
  readAssistantControls,
  undoLastAssistantRequest,
  undoableAssistantChanges,
  searchAssistantOptions,
  type AssistantControl,
} from "../../src/lib/assistantControls";
import { MAX_PLOT_DIMENSION_CM, MAX_PLOT_DPI, MIN_PLOT_DIMENSION_CM, MIN_PLOT_DPI } from "../../src/lib/plotLimits";

function Surface({ children }: { children: ReactNode }) {
  return <AssistantSurface module="test" enabled>{children}</AssistantSurface>;
}

const noop = () => {};

it("waits for canvas images to settle, including failed renders", () => {
  const canvas = (busy: boolean) => <Surface><section data-assistant-tile="boxplot">
    <img aria-busy={busy} alt="analysis boxplot" />
  </section></Surface>;
  const { rerender, unmount } = render(canvas(true));
  expect(assistantSurfaceReady("test")).toBe(false);
  // Both successful and failed image loads clear the busy flag.
  rerender(canvas(false));
  expect(assistantSurfaceReady("test")).toBe(true);
  expect(assistantSurfaceReady("another-module")).toBe(false);
  rerender(canvas(true));
  expect(assistantSurfaceReady("test")).toBe(false);
  unmount();
  expect(assistantSurfaceReady("test")).toBe(false);
});

/** A text field the assistant can set, with its caption as its label. */
function Field({ label, initial = "1", appearance = false }: { label: string; initial?: string; appearance?: boolean }) {
  const [value, setValue] = useState(initial);
  return (
    <label data-assistant-appearance={appearance ? "true" : undefined}>
      <span>{label}</span>
      <AssistantInput type="text" data-assistant-permission={appearance ? "view" : undefined}
        value={value} onChange={(event) => setValue(event.target.value)} />
    </label>
  );
}

/** A drop-down named by its aria-label, as the plot pages name theirs. */
function Choice({ name, options, initial, labels = {}, multiple = false, view = false }: {
  name: string; options: string[]; initial?: string; labels?: Record<string, string>; multiple?: boolean; view?: boolean;
}) {
  const [value, setValue] = useState<string | string[]>(multiple ? [] : initial ?? options[0]);
  return (
    <AssistantSelect aria-label={name} multiple={multiple} value={value} data-assistant-permission={view ? "view" : undefined}
      onChange={(event) => setValue(multiple ? Array.from(event.target.selectedOptions).map((option) => option.value) : event.target.value)}>
      {options.map((option, index) => <option key={`${option}-${index}`} value={option}>{labels[option] ?? option}</option>)}
    </AssistantSelect>
  );
}

const byLabel = (label: string, question = "", searches: Record<string, string> = {}) =>
  readAssistantControls(question, searches).find((control) => control.label === label) as AssistantControl;

describe("numeric fields", () => {
  it("expose the plot size as bounded cosmetic controls without changing other numeric permissions", () => {
    const { container } = render(<Surface>
      <NumberField label="Threshold" value={1} onChange={noop} />
      <SizeRow widthCm={20} heightCm={10} dpi={300} onWidthChange={noop} onHeightChange={noop} onDpiChange={noop} />
    </Surface>);
    const threshold = byLabel("Threshold");
    expect(threshold.appearance).toBe(false);
    expect(threshold.permission).toBe("confirm");
    expect(Array.from(container.querySelectorAll("label")).map((label) => label.textContent))
      .toEqual(["Threshold", "Width (cm)", "Height (cm)", "DPI"]);
    for (const [label, min, max] of [["Width (cm)", MIN_PLOT_DIMENSION_CM, MAX_PLOT_DIMENSION_CM],
      ["Height (cm)", MIN_PLOT_DIMENSION_CM, MAX_PLOT_DIMENSION_CM], ["DPI", MIN_PLOT_DPI, MAX_PLOT_DPI]] as const) {
      const control = byLabel(label);
      expect(control.appearance, label).toBe(true);
      expect(control.permission, label).toBe("view");
      expect([control.min, control.max], label).toEqual([min, max]);
    }
  });
});

describe("reading the controls", () => {
  it("carries every enclosing group in a label, so the X and Y axis labels differ", () => {
    render(<Surface>
      <div data-assistant-group="X axis"><div data-assistant-group="Axis label"><Field label="Text" /></div></div>
      <div data-assistant-group="Y axis"><div data-assistant-group="Axis label"><Field label="Text" /></div></div>
      <div data-assistant-group="Title"><div data-assistant-group="Title"><Field label="Size" /></div></div>
      <Field label="Ungrouped" />
    </Surface>);
    expect(readAssistantControls().map((control) => control.label).sort())
      .toEqual(["Title / Size", "Ungrouped", "X axis / Axis label / Text", "Y axis / Axis label / Text"]);
  });

  it("does not report a different view when a control re-registers", () => {
    function Rerendering() {
      const [count, setCount] = useState(0);
      return <div data-assistant-group="Title">
        <button type="button" onClick={() => setCount(count + 1)}>Re-render</button>
        <Field label="Size" initial="12" />
      </div>;
    }
    // The re-rendered control registers again, which moves it to the end of
    // the registry: it was first before.
    render(<Surface>
      <Rerendering />
      <div data-assistant-group="Title"><Field label="Size" initial="12" /></div>
    </Surface>);
    const before = readAssistantControls();
    fireEvent.click(screen.getByText("Re-render"));
    expect(readAssistantControls()).toEqual(before);
  });

  it("lets an unnamed cosmetic setting yield to an analysis control at the transport cap", () => {
    render(<Surface>
      <div data-assistant-group="Title">
        {Array.from({ length: 120 }, (_, index) => <Field key={index} label={`Setting ${index}`} appearance />)}
      </div>
      <Choice name="Protein / Site" options={["K1"]} />
      <Field label="Z-score cutoff" />
      <div data-assistant-group="Legend"><Field label="Text size" initial="10" appearance /></div>
    </Surface>);
    const shown = readAssistantControls("Which site is selected?");
    expect(shown.length).toBe(100);
    expect(shown[0].label).toBe("Protein / Site");
    // An analysis control the question does not name still makes the cut.
    expect(readAssistantControls("").some((control) => control.label === "Z-score cutoff")).toBe(true);
    // A named cosmetic setting still comes first when the question asks for it.
    expect(readAssistantControls("Make the legend smaller.")[0].label).toBe("Legend / Text size");
  });

  it("searches the displayed option names but keeps the machine value", () => {
    render(<Surface><div data-assistant-group="Font">
      <Choice name="All text" options={["helvetica", "times"]} labels={{ helvetica: "Helvetica / Arial", times: "Times New Roman" }} />
    </div></Surface>);
    const font = byLabel("Font / All text");
    const found = byLabel("Font / All text", "Which fonts are available?", { [font.id]: "new roman" });
    expect(found.options).toEqual(["times"]);
    expect(found.optionMatchCount).toBe(1);
    expect(found.value).toBe("helvetica");
  });

  it("finds a site written as gene and position in a spaced search", () => {
    // "RIF1 S1542" names Q5UIP0~RIF1_S1542_M1 (GRK project, 2026-10-14).
    render(<Surface><Choice name="Protein / Site" initial="A~CDK1_T14_M2"
      options={["A~CDK1_T14_M2", "Q5UIP0~RIF1_S1542_M1", "Q5UIP0~RIF1_S2205_M1", "X~SERBP1_T388_M1"]} /></Surface>);
    const site = byLabel("Protein / Site");
    expect(byLabel("Protein / Site", "", { [site.id]: "RIF1 S1542" }).options).toEqual(["Q5UIP0~RIF1_S1542_M1"]);
    expect(byLabel("Protein / Site", "", { [site.id]: "rif1" }).options).toEqual(["Q5UIP0~RIF1_S1542_M1", "Q5UIP0~RIF1_S2205_M1"]);
  });

  it("keeps the page's selectors ahead of grouped per-condition settings under the 100-control cap", () => {
    // 16 conditions x colour and name rows pushed "Protein / Site" past the cap when the question
    // did not say "protein" (GRK project, 2026-10-14).
    const conditions = Array.from({ length: 16 }, (_, i) => `K${i}`);
    render(<Surface>
      <Choice name="Identifier" options={["workflow", "genes"]} />
      <Choice name="Protein / Site" initial="P1" options={["P1", "P2"]} />
      {conditions.flatMap((c) => [
        <div key={`${c}c`} data-assistant-group="Boxes and their points / Box border color"><Choice name={c} options={["#000", "#fff"]} /></div>,
        <div key={`${c}n`} data-assistant-group="Names and colors / Condition names"><Choice name={c} options={[c, `${c}x`]} /></div>,
        <div key={`${c}s`} data-assistant-group="Lines and markers / Condition styles"><Choice name={c} options={["solid", "dashed"]} /></div>,
        <div key={`${c}m`} data-assistant-group="Lines and markers / Condition markers"><Choice name={c} options={["o", "x"]} /></div>,
      ])}
      {Array.from({ length: 40 }, (_, i) => <div key={`g${i}`} data-assistant-group="Axes and ticks / Ticks"><Choice name={`Tick ${i}`} options={["a", "b"]} /></div>)}
    </Surface>);
    const labels = readAssistantControls("Show me RIF1 S1542 across all 16 conditions so I can see the baseline and the 5 minute response in every line.").map((c) => c.label);
    expect(labels.length).toBe(100);
    expect(labels).toContain("Protein / Site");
    expect(labels).toContain("Identifier");
    expect(isGroupedSetting("Protein / Site")).toBe(false);
    expect(isGroupedSetting("Names and colors / Condition colors / C0")).toBe(true);
  });

  it("handles exact matches, empty results and read-only discovery in a targeted option search", () => {
    render(<Surface><Choice name="Protein" initial="P1" options={Array.from({ length: 100 }, (_, i) => `P${i}`)} /></Surface>);
    const protein = byLabel("Protein");
    expect(protein.options.length).toBe(40);
    expect(searchAssistantOptions(protein.id, " P99 ")).toBe("P99");
    expect(byLabel("Protein", "", { [protein.id]: "P99" }).options).toEqual(["P99"]);
    const missing = byLabel("Protein", "", { [protein.id]: "absent" });
    expect(missing.optionMatchCount).toBe(0);
    expect(missing.options).toEqual([]);
    expect(missing.value).toBe("P1");
    expect(() => searchAssistantOptions("missing", "P1")).toThrow();
    expect(() => searchAssistantOptions(protein.id, "")).toThrow();
  });
});

describe("hidden controls", () => {
  const readable = () => readAssistantControls().map((control) => control.label).sort();

  it("stay readable inside the offscreen appearance mount, while ordinary hiding still counts", () => {
    render(<Surface>
      <AssistantAppearanceMount visible={false}>
        <Field label="In the mount" />
        <div hidden><Field label="Hidden in the mount" /></div>
        <div aria-hidden="true"><Field label="Aria-hidden in the mount" /></div>
      </AssistantAppearanceMount>
      <div inert><AssistantAppearanceMount visible={false}><Field label="Mount under a modal" /></AssistantAppearanceMount></div>
      <div aria-hidden="true"><div><Field label="Aria-hidden page" /></div></div>
      <div><Field label="Plain" /></div>
    </Surface>);
    expect(readable()).toEqual(["In the mount", "Plain"]);
  });

  it("are mounted offscreen and inert rather than unmounted while the user keeps the panel closed", () => {
    const { rerender } = render(<AssistantAppearanceMount visible={false}><p>Panel</p></AssistantAppearanceMount>);
    const host = screen.getByText("Panel").parentElement!;
    expect(host.getAttribute("data-assistant-offscreen")).toBe("true");
    expect(host.getAttribute("aria-hidden")).toBe("true");
    expect(host.hasAttribute("inert")).toBe(true);
    rerender(<AssistantAppearanceMount visible><p>Panel</p></AssistantAppearanceMount>);
    expect(screen.getByText("Panel").closest("[data-assistant-offscreen]")).toBeNull();
    expect(screen.getByText("Panel").closest("[aria-hidden],[inert]")).toBeNull();
  });
});

describe("feature candidates", () => {
  function featureId(label: string) {
    return byLabel(label).id;
  }

  it("use the full live options but never guess an exact or multiple selection", () => {
    const { rerender } = render(<Surface><Choice name="Protein / Site" options={Array.from({ length: 80 }, (_, i) => `K${i}`)} /></Surface>);
    const id = featureId("Protein / Site");
    expect(assistantFeatureChoices(id, "K")).toMatch(/80 matches/);
    expect(assistantFeatureChoices(id, "K")).toMatch(/first 5/);
    expect(assistantFeatureChoices(id, "k79")).toBe("");
    expect(assistantFeatureChoices(id, "missing")).toBe("");
    expect(assistantFeatureChoices("absent", "K")).toBe("");

    rerender(<Surface><Choice name="Protein / Site" options={["AKT1", "AKT2", "AKT2"]} /></Surface>);
    expect(assistantFeatureChoices(featureId("Protein / Site"), "AKT")).toMatch(/2 matches: "AKT1", "AKT2"/);
    rerender(<Surface><Choice name="Condition" options={["AKT1", "AKT2"]} /></Surface>);
    expect(assistantFeatureChoices(featureId("Condition"), "AKT")).toBe("");
    rerender(<Surface><div data-assistant-group="Tile 1: proteinBoxplot"><Choice name="Protein or gene" options={["AKT1", "AKT2"]} /></div></Surface>);
    expect(assistantFeatureChoices(featureId("Tile 1: proteinBoxplot / Protein or gene"), "AKT")).toMatch(/2 matches/);
    rerender(<Surface><Choice name="Protein / Site" multiple options={["AKT1", "AKT2"]} /></Surface>);
    expect(assistantFeatureChoices(featureId("Protein / Site"), "AKT")).toBe("");
  });

  it("list every prefix match for a prefix request even when one matches exactly", () => {
    render(<Surface><Choice name="Protein / Site" options={["K7", "K17", ...Array.from({ length: 10 }, (_, i) => `K7${i}`)]} /></Surface>);
    const id = featureId("Protein / Site");
    expect(assistantFeatureChoices(id, "K7"), "without prefix intent an exact match is selectable").toBe("");
    const listed = assistantFeatureChoices(id, "K7", "Find the site whose identifier starts with K7");
    expect(listed).toMatch(/11 matches: "K7", "K70"/);
    expect(listed).not.toMatch(/K17/);
  });
});

describe("applying changes", () => {
  it("rejects a batch that sets one control twice before any change or confirmation", () => {
    render(<Surface><Field label="Width" initial="5" /></Surface>);
    const width = byLabel("Width");
    expect(width.permission).toBe("confirm");
    expect(() => applyAssistantControls([
      { type: "set_control", target: width.id, value: "10" },
      { type: "set_control", target: width.id, value: "20" },
    ])).toThrow(/only once per batch/);
    expect(byLabel("Width").value).toBe("5");
  });
});

describe("adding canvas tiles", () => {
  const state = { wrong: false, failAt: Infinity };

  function Canvas() {
    const [tiles, setTiles] = useState<[string, string][]>([["existing", "volcano"]]);
    const [type, setType] = useState("volcano");
    return (
      <Surface>
        <AssistantSelect aria-label="New tile type" data-assistant-permission="view" value={type} onChange={(event) => setType(event.target.value)}>
          {["volcano", "proteinBoxplot", "oraList"].map((option) => <option key={option} value={option}>{option}</option>)}
        </AssistantSelect>
        <AssistantCanvasButton effect="add" onClick={() => {
          if (tiles.length >= state.failAt) throw new Error("Unavailable");
          setTiles([...tiles, [`new-${tiles.length}`, state.wrong ? "oraList" : type]]);
        }}>+ Add Plot</AssistantCanvasButton>
        {tiles.map(([id, tileType]) => <div key={id} data-assistant-tile={id} data-assistant-tile-type={tileType} />)}
      </Surface>
    );
  }
  const tiles = () => Array.from(document.querySelectorAll("[data-assistant-tile]")).map((tile) =>
    [tile.getAttribute("data-assistant-tile"), tile.getAttribute("data-assistant-tile-type")]);

  it("validates the request and stops on a wrong-type or partial addition", () => {
    render(<Canvas />);
    const receipts: string[] = [];
    for (const value of [null, "{}", '{"type":"proteinBoxplot","count":9}', '{"type":"proteinBoxplot","count":1.5}', '{"type":"__proto__","count":1}']) {
      expect(() => addCanvasTiles(value as unknown as string, 8, (receipt) => receipts.push(receipt))).toThrow();
    }
    expect(tiles().length).toBe(1);
    expect(addCanvasTiles('{"type":"proteinBoxplot","count":2}', 8, (receipt) => receipts.push(receipt))).toMatch(/Added 2 Protein Boxplot tiles/);
    expect(receipts.length).toBe(2);
    expect(tiles()[0]).toEqual(["existing", "volcano"]);
    expect(tiles().slice(1).map(([, type]) => type)).toEqual(["proteinBoxplot", "proteinBoxplot"]);
    expect(() => addCanvasTiles('{"type":"volcano","count":2}', 1, noop)).toThrow();

    state.wrong = true;
    expect(() => addCanvasTiles('{"type":"volcano","count":1}', 8, () => expect.unreachable())).toThrow(/confirm the requested plot type/);
    state.wrong = false;
    state.failAt = tiles().length + 1;
    const partial: string[] = [];
    expect(() => addCanvasTiles('{"type":"volcano","count":2}', 8, (receipt) => partial.push(receipt))).toThrow(/Unavailable/);
    expect(partial.length).toBe(1);
  });
});

describe("undo covers the last request only", () => {
  it("takes back every change of the latest request and leaves earlier requests alone", () => {
    const { unmount } = render(<Surface><Field label="Title size" initial="12" appearance /><Field label="Width" initial="5" appearance /></Surface>);
    const size = () => byLabel("Title size"), width = () => byLabel("Width");
    beginAssistantRequest();
    applyAssistantControls([{ type: "set_control", target: size().id, value: "20" }]);
    beginAssistantRequest();
    applyAssistantControls([{ type: "set_control", target: width().id, value: "9" }]);
    applyAssistantControls([{ type: "set_control", target: size().id, value: "24" }]);
    expect(undoableAssistantChanges().map((change) => change.label)).toEqual(["Width", "Title size"]);
    const logged = assistantChanges().length;  // the session log also holds earlier tests' changes
    expect(undoLastAssistantRequest()).toBe("Undid 2 changes of the last request.");
    expect(size().value).toBe("20");  // the first request's change stays
    expect(width().value).toBe("5");
    expect(undoableAssistantChanges()).toHaveLength(0);
    expect(assistantChanges()).toHaveLength(logged - 2);
    expect(() => undoLastAssistantRequest()).toThrow(/no assistant change to undo/);
    unmount();
  });
});

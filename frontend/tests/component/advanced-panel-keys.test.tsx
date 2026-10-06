/**
 * The advanced plot panel writes the backend's settings vocabulary, all of it.
 *
 * The panel is rendered with every card shown, and every field, box and list in
 * it is changed, pass after pass, until no new control appears (some appear
 * only once a box is ticked, others only while one stays unticked, so the sweep
 * runs once with the boxes clicked and once without). The keys that reach
 * `onChange` are the panel's real vocabulary. They are compared with
 * `AdvancedPlotSettings` in the generated OpenAPI schema
 * (backend/app/schemas/plot_settings.py), whose renderer side is checked by
 * tests/contracts/test_advanced_settings_reach_the_renderers.py.
 *
 * This replaced a scan of the panel's source with regular expressions, which
 * had missed 35 of the keys the panel writes.
 */
import { fireEvent, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import AdvancedPlotOptions, {
  type AdvancedPlotVisibleControls,
} from "../../src/components/plots/AdvancedPlotOptions";
import { compactAdvancedPlotSettings } from "../../src/lib/plotSerialization";
import type { AdvancedPlotSettings } from "../../src/lib/types";

type PropertySchema = {
  anyOf?: { enum?: string[]; additionalProperties?: { enum?: string[] } }[];
  "x-panel"?: boolean;
};
const openapi = JSON.parse(
  readFileSync(resolve(__dirname, "../../src/lib/generated/openapi.json"), "utf-8")
);
const PROPERTIES: Record<string, PropertySchema> =
  openapi.components.schemas.AdvancedPlotSettings.properties;
const PANEL_KEYS = Object.keys(PROPERTIES).filter((key) => PROPERTIES[key]["x-panel"] !== false);

/** The values an enumerated setting may take, or null for a free one. */
function allowedValues(key: string): string[] | null {
  for (const branch of PROPERTIES[key].anyOf ?? []) {
    const values = branch.enum ?? branch.additionalProperties?.enum;
    if (values) return values;
  }
  return null;
}

const EVERY_CARD: AdvancedPlotVisibleControls = {
  textElements: true, tickControls: true, legendControls: true, referenceLineColor: true,
  referenceLineToggle: true, fontControls: true, conditionLabels: true, sampleLabels: true,
  conditionColors: true, boxplotStyle: true, boxplotOutliers: true, boxplotPoints: true,
  correlationGradient: true, backgroundControls: true, axisLineControls: true, markerStyle: true,
  conditionMarkers: true, markerColor: true, volcanoMarkers: true, barColor: true, rowLabels: true,
  phosphoClassColors: true, vennColors: true, valueLabels: true,
};

type Sweep = {
  written: Set<string>;
  /** For each key a list wrote, every value that list offered. */
  offered: Map<string, Set<string>>;
  final: AdvancedPlotSettings;
};

function sweep(clickBoxes: boolean): Sweep {
  const written = new Set<string>();
  const offered = new Map<string, Set<string>>();
  let final: AdvancedPlotSettings = {};
  let current: HTMLInputElement | HTMLSelectElement | null = null;

  function Harness() {
    const [value, setValue] = useState<AdvancedPlotSettings>({});
    return (
      <AdvancedPlotOptions
        value={value}
        onChange={(next) => {
          for (const key of Object.keys(next) as (keyof AdvancedPlotSettings)[]) {
            if (JSON.stringify(next[key]) === JSON.stringify(value[key])) continue;
            written.add(key);
            // A list can write a second key with the one it names (switching
            // the grid on also stores its style); only the key that took the
            // list's value is the list's.
            const took = next[key];
            const tookValue =
              took === current?.value ||
              (typeof took === "object" && took !== null && Object.values(took).includes(current?.value));
            if (current instanceof HTMLSelectElement && tookValue) {
              const values = offered.get(key) ?? new Set<string>();
              for (const option of Array.from(current.options)) values.add(option.value);
              offered.set(key, values);
            }
          }
          final = next;
          setValue(next);
        }}
        conditionOptions={["A", "B"]}
        sampleOptions={["A_1", "B_1"]}
        visibleControls={EVERY_CARD}
      />
    );
  }

  const { container, unmount } = render(<Harness />);
  const touched = new WeakSet<Element>();
  let count = 0;
  for (let pass = 0; pass < 8; pass += 1) {
    const fresh = Array.from(container.querySelectorAll("input, select, textarea")).filter(
      (field) => !touched.has(field)
    );
    if (!fresh.length) break;
    for (const field of fresh) {
      touched.add(field);
      current = field as HTMLInputElement | HTMLSelectElement;
      if (field instanceof HTMLSelectElement) {
        const other = Array.from(field.options).find((option) => option.value && option.value !== field.value);
        if (other) fireEvent.change(field, { target: { value: other.value } });
      } else if (field instanceof HTMLInputElement && field.type === "checkbox") {
        if (clickBoxes) fireEvent.click(field);
      } else if (field instanceof HTMLInputElement && field.type === "color") {
        fireEvent.change(field, { target: { value: "#123457" } });
      } else {
        const input = field as HTMLInputElement;
        // A number field rejects text and a text field takes anything, so a
        // number is tried first and text only if the field would not keep it.
        // Each field gets its own value: one that merely repeats what the field
        // already shows (a class size following the general size) is no change.
        count += 1;
        const number = String(0.6 + (count % 30) / 100);
        fireEvent.change(input, { target: { value: number } });
        fireEvent.blur(input);
        if (input.value !== number) {
          fireEvent.change(input, { target: { value: `x${count}` } });
          fireEvent.blur(input);
        }
      }
    }
  }
  current = null;
  unmount();
  return { written, offered, final };
}

describe("the advanced panel's vocabulary", () => {
  const clicked = sweep(true);
  const unclicked = sweep(false);
  const written = new Set([...clicked.written, ...unclicked.written]);

  it("the sweep reaches the whole panel", () => {
    expect(written.size).toBeGreaterThan(80);
  });

  it("writes only keys the backend declares", () => {
    expect([...written].filter((key) => !(key in PROPERTIES)).sort()).toEqual([]);
  });

  it("can write every key the backend declares for it", () => {
    expect(PANEL_KEYS.filter((key) => !written.has(key)).sort()).toEqual([]);
  });

  it("offers exactly the values the renderers know, in every list", () => {
    const mismatched: string[] = [];
    for (const { offered } of [clicked, unclicked]) {
      for (const [key, values] of offered) {
        const allowed = allowedValues(key);
        if (!allowed) continue;
        const shown = [...values].filter(Boolean).sort();
        if (JSON.stringify(shown) !== JSON.stringify([...allowed].sort())) {
          mismatched.push(`${key}: panel ${shown.join(",")} / backend ${[...allowed].sort().join(",")}`);
        }
      }
    }
    expect(mismatched).toEqual([]);
    // Each enumerated key the panel writes was written by a list.
    const enumerated = PANEL_KEYS.filter((key) => allowedValues(key));
    expect(enumerated.filter((key) => !clicked.offered.has(key) && !unclicked.offered.has(key))).toEqual([]);
  });

  it("the URL keeps every setting the panel stored", () => {
    // The compaction once dropped whole groups of keys on one page, so the
    // panel stored a setting the plot never received.
    for (const { final } of [clicked, unclicked]) {
      const sent = compactAdvancedPlotSettings(final);
      // A key set back to nothing -- a class size cleared by the general one, an
      // override map emptied -- is rightly not sent.
      const stored = Object.entries(final).filter(
        ([, value]) => value !== undefined && !(typeof value === "object" && !Object.keys(value).length)
      );
      const dropped = stored.map(([key]) => key).filter((key) => !(key in sent));
      expect(dropped).toEqual([]);
    }
  });
});

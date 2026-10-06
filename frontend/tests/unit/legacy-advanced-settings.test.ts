/**
 * Settings an older panel wrote come back in the current panel's keys.
 *
 * The single frame switch (`axisLineVisible`) became four per-side boxes and the
 * value-label offsets (`textXOffset`/`textYOffset`) lost their control. A saved
 * session can still hold them; restored as they were, the panel would show
 * four ticked boxes over a plot drawn without a frame. They are migrated where
 * saved settings are read and before a plot URL is built. The backend half is
 * tests/unit/plots/test_legacy_advanced_settings.py.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { getAdvancedPlotSettingsByKey } from "../../src/lib/appSettings";
import { compactAdvancedPlotSettings, migrateAdvancedPlotSettings } from "../../src/lib/plotSerialization";
import type { AdvancedPlotSettings } from "../../src/lib/types";

const legacy = (value: Record<string, unknown>) => value as AdvancedPlotSettings;
const SIDES = ["axisLineTop", "axisLineRight", "axisLineBottom", "axisLineLeft"] as const;

beforeEach(() => sessionStorage.clear());

describe("an older panel's settings", () => {
  it.each([true, false])("turn the frame switch %s into four sides", (frame) => {
    const migrated = migrateAdvancedPlotSettings(legacy({ axisLineVisible: frame, axisLineColor: "#123456" }));
    expect(migrated).toEqual({ axisLineColor: "#123456", ...Object.fromEntries(SIDES.map((side) => [side, frame])) });
  });

  it("keep a side that was set on its own", () => {
    const migrated = migrateAdvancedPlotSettings(legacy({ axisLineVisible: false, axisLineLeft: true }));
    expect(migrated.axisLineLeft).toBe(true);
    expect(migrated.axisLineBottom).toBe(false);
  });

  it("drop the value-label offsets", () => {
    expect(migrateAdvancedPlotSettings(legacy({ textXOffset: 3, textYOffset: 1, valueLabelSize: 8 }))).toEqual({
      valueLabelSize: 8,
    });
  });

  it("never reach a plot URL in the old keys", () => {
    const sent = compactAdvancedPlotSettings(legacy({ axisLineVisible: false, textXOffset: 3 }));
    expect(sent).not.toHaveProperty("axisLineVisible");
    expect(sent).not.toHaveProperty("textXOffset");
    expect(SIDES.map((side) => sent[side])).toEqual([false, false, false, false]);
  });

  it("are migrated when a restored session is read back", () => {
    sessionStorage.setItem(
      "copylot:advancedPlotSettingsByKey.v2",
      JSON.stringify({ "stats:volcano": { axisLineVisible: false, textYOffset: 2, markerSize: 4 } })
    );
    expect(getAdvancedPlotSettingsByKey()["stats:volcano"]).toEqual({
      markerSize: 4,
      ...Object.fromEntries(SIDES.map((side) => [side, false])),
    });
  });
});

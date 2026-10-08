/**
 * Width, height and DPI are one control with one set of limits.
 *
 * Every plot is sized by the same row: width, then height, then DPI, clamped to
 * the limits the backend enforces (src/lib/generated/plotLimits.json, written
 * from backend/app/services/plot_limits.py and checked for staleness by
 * tests/contracts/test_generated_api_is_current.py). A saved size that is
 * missing or malformed falls back to the page's default, never to 0 cm.
 *
 * The rules about where a page may size a plot -- only through this row, with
 * no clamp of its own and no bare `Number(saved.widthCm)` -- are lint rules in
 * eslint.config.js. Together these replace a scan of every page's source.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SizeRow } from "../../src/components/PlotFields";
import limits from "../../src/lib/generated/plotLimits.json";
import { restorePlotDimensionCm, restorePlotDpi } from "../../src/lib/plotLimits";

function row() {
  const changes = { width: vi.fn(), height: vi.fn(), dpi: vi.fn() };
  render(
    <SizeRow widthCm={20} heightCm={12} dpi={300}
      onWidthChange={changes.width} onHeightChange={changes.height} onDpiChange={changes.dpi} />
  );
  return changes;
}

function enter(label: string, value: string) {
  const input = screen.getByLabelText(label, { exact: false, selector: "input" }) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
}

describe("the size row", () => {
  it("asks for width, then height, then DPI", () => {
    row();
    const labels = Array.from(document.querySelectorAll("label")).map((label) => label.textContent);
    expect(labels).toEqual(["Width (cm)", "Height (cm)", "DPI"]);
  });

  it("clamps to the backend's limits, and nothing narrower", () => {
    const changes = row();
    enter("Width (cm)", "9999");
    enter("Height (cm)", "0.01");
    enter("DPI", "100000");
    expect(changes.width).toHaveBeenLastCalledWith(limits.MAX_PLOT_WIDTH_CM);
    expect(changes.height).toHaveBeenLastCalledWith(limits.MIN_PLOT_HEIGHT_CM);
    expect(changes.dpi).toHaveBeenLastCalledWith(limits.MAX_PLOT_DPI);

    // The smallest figure the backend draws is accepted as it is.
    enter("Width (cm)", String(limits.MIN_PLOT_WIDTH_CM));
    expect(changes.width).toHaveBeenLastCalledWith(limits.MIN_PLOT_WIDTH_CM);
  });
});

describe("a saved size", () => {
  it.each([null, undefined, "", "  ", "abc", Number.NaN])("falls back to the default when it is %s", (saved) => {
    expect(restorePlotDimensionCm(saved, 18)).toBe(18);
    expect(restorePlotDpi(saved, 300)).toBe(300);
  });

  it("is read as a number when it is one, in either decimal notation", () => {
    expect(restorePlotDimensionCm("3,5", 18)).toBe(3.5);
    expect(restorePlotDimensionCm(7, 18)).toBe(7);
    expect(restorePlotDpi("150", 300)).toBe(150);
  });

  it("is clamped like a typed one, and so is the default", () => {
    expect(restorePlotDimensionCm(9999, 18)).toBe(limits.MAX_PLOT_WIDTH_CM);
    expect(restorePlotDpi(1, 300)).toBe(limits.MIN_PLOT_DPI);
    expect(restorePlotDimensionCm(null, 0)).toBe(limits.MIN_PLOT_WIDTH_CM);
  });
});
